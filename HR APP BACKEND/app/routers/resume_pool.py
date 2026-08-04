import asyncio
import logging
from typing import Awaitable, Callable, List
from importlib import import_module

from fastapi import HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Candidate, JobDescription, User
from app.services.auth_service import log_action


class _LazyModule:
    def __init__(self, module_path: str):
        self._module_path = module_path
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = import_module(self._module_path)
        return self._module

    def __getattr__(self, item):
        return getattr(self._load(), item)


gemini_service = _LazyModule("app.services.gemini_service")
scoring_service = _LazyModule("app.services.scoring_service")
harness_agent_client = _LazyModule("app.services.harness_agent_client")


def _is_harness_or_timeout_error(exc: Exception) -> bool:
    return isinstance(exc, asyncio.TimeoutError) or exc.__class__.__name__ == "HarnessAgentError"


class ImportFromPoolRequest(BaseModel):
    job_id: str
    candidate_ids: List[str]


async def _run_resume_scorer_with_fallback(
    *,
    request: Request,
    parsed_resume: dict,
    job: JobDescription,
) -> dict:
    try:
        result = await harness_agent_client.run_agent(
            "resume_scorer",
            {
                "parsed_resume": parsed_resume,
                "job_title": job.title,
                "exp_min": job.experience_min,
                "exp_max": job.experience_max,
                "must_have": job.must_have_skills or [],
                "good_to_have": job.good_to_have_skills or [],
                "description": job.description or "",
                "jd_embedding": job.embedding or [],
            },
            request.headers.get("authorization"),
        )
        if isinstance(result, dict) and isinstance(result.get("score_result"), dict):
            return result["score_result"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning(
            "Harness fallback resume_scorer (import-from-pool) failed, using direct scorer: %s",
            runtime_exc,
        )
        return await gemini_service.score_resume_against_jd(
            parsed_resume=parsed_resume,
            job_title=job.title,
            exp_min=job.experience_min,
            exp_max=job.experience_max,
            must_have=job.must_have_skills or [],
            good_to_have=job.good_to_have_skills or [],
            description=job.description or "",
        )


async def import_from_pool_impl(
    request: Request,
    body: ImportFromPoolRequest,
    db: AsyncSession,
    user: User,
    *,
    logger: logging.Logger,
    assert_job_owner: Callable[[str, User, AsyncSession], Awaitable[JobDescription]],
    jd_signature_hash: Callable[[JobDescription], str],
    job_has_meaningful_criteria: Callable[[JobDescription], bool],
    recompute_job_rank_and_tags: Callable[[AsyncSession, JobDescription], Awaitable[None]],
):
    job = await assert_job_owner(body.job_id, user, db)
    imported, skipped = 0, 0
    skipped_unauthorized_set: set[str] = set()

    from sqlalchemy import or_ as _or_import
    unauthorized_rows = (await db.execute(
        select(Candidate.id).where(
            Candidate.id.in_(body.candidate_ids),
            Candidate.job_id.is_(None),
            _or_import(Candidate.user_id.is_(None), Candidate.user_id != user.id),
        )
    )).scalars().all()
    skipped_unauthorized_set.update(str(cid) for cid in unauthorized_rows if cid)

    # BUG 5 FIX: batch-fetch all candidates in one query instead of N individual
    # SELECT statements inside the loop (was 50 round-trips for 50 imports).
    pool_rows = (await db.execute(
        select(Candidate).where(
            Candidate.id.in_(body.candidate_ids),
            Candidate.job_id.is_(None),
            Candidate.user_id == user.id,
        )
    )).scalars().all()
    candidates_map: dict[str, Candidate] = {c.id: c for c in pool_rows}

    _current_jd_hash = jd_signature_hash(job)

    ai_sem_import = asyncio.Semaphore(10)

    async def _import_task(cid: str) -> bool:
        c = candidates_map.get(cid)
        if c is None:
            return False
        if c.user_id != user.id:
            skipped_unauthorized_set.add(cid)
            return False

        exp_years = float(c.experience_years or 0)
        skill_years_c = (c.skill_years or {})

        skill_pct = scoring_service.skill_match_score(
            c.normalized_skills or [], job.must_have_skills or [], job.good_to_have_skills or []
        )
        exp_pct = scoring_service.experience_match_score(
            exp_years, job.experience_min, job.experience_max, skill_years_c, job.must_have_skills or []
        )
        proj_pct = scoring_service.project_relevance_score(
            c.projects or [], job.must_have_skills or [], job.good_to_have_skills or [], exp_years
        )
        edu_pct = scoring_service.education_match_score(
            c.education or [],
            experience_years=exp_years,
            jd_description=job.description or "",
            jd_must_have=job.must_have_skills or [],
            jd_education_requirement=getattr(job, "education_requirement", None),
        )
        loc_pct = scoring_service.location_match_score(getattr(c, "location", None), job.location)
        try:
            vec_sim = scoring_service.cosine_similarity(c.embedding or [], job.embedding or [])
        except ValueError as vec_err:
            logger.warning("[import-from-pool] Vector similarity degraded for candidate %s: %s", cid, vec_err)
            vec_sim = 0.0

        ai_scores: dict | None = None

        if (
            c.score_breakdown
            and c.score_breakdown.get("ai_score_used") is True
            and c.score_breakdown.get("jd_hash") == _current_jd_hash
        ):
            bd = c.score_breakdown
            ai_scores = {
                "skill_score":          bd.get("ai_skill_score", 50),
                "experience_score":     bd.get("ai_experience_score", 50),
                "project_score":        bd.get("ai_project_score", 50),
                "matched_must_have":    bd.get("matched_must_have", []),
                "missing_must_have":    bd.get("missing_must_have", []),
                "matched_good_to_have": bd.get("matched_good_to_have", []),
                "reasoning":            bd.get("reasoning", ""),
                "domain_fit":           bd.get("domain_fit", "exact"),
                "seniority_match":      bd.get("seniority_match", "exact"),
                "hire_recommendation":  bd.get("hire_recommendation", "maybe"),
                "red_flags":            bd.get("red_flags", []),
                "standout_factors":     bd.get("standout_factors", []),
                "confidence":           bd.get("confidence", "medium"),
            }
            logger.info("[import-from-pool] JD-matched cache hit for candidate %s", cid)
        else:
            try:
                parsed_resume = {
                    "name":              c.name,
                    "email":             c.email,
                    "location":          getattr(c, "location", None),
                    "experience_years":  exp_years,
                    "normalized_skills": c.normalized_skills or [],
                    "skill_years":       skill_years_c,
                    "work_experience":   c.work_experience or [],
                    "projects":          c.projects or [],
                    "education":         c.education or [],
                }
                async with ai_sem_import:
                    ai_scores = await _run_resume_scorer_with_fallback(
                        request=request,
                        parsed_resume=parsed_resume,
                        job=job,
                    )
            except Exception:
                logger.warning("[import-from-pool] AI scoring failed for %s", cid)

        has_jd_criteria = job_has_meaningful_criteria(job)
        phase_b_weights, phase_b_bias, phase_b_meta = scoring_service.build_phase_b_calibration(
            experience_years=exp_years,
            job_title=job.title,
            job_role=job.role,
            jd_description=job.description or "",
            jd_must_have=job.must_have_skills or [],
            jd_good_to_have=job.good_to_have_skills or [],
            exp_min=job.experience_min,
            exp_max=job.experience_max,
        )

        missing_must_count = sum(
            1
            for skill in (job.must_have_skills or [])
            if not scoring_service.semantic_skill_match(skill, c.normalized_skills or [])
        )

        final_score, used_skill_pct, used_exp_pct, used_proj_pct = (
            scoring_service.compute_resume_score_with_ai_override(
                ai_scores=ai_scores,
                education_pct=edu_pct,
                vector_sim=vec_sim,
                location_pct=loc_pct,
                experience_years=exp_years,
                rule_skill_pct=skill_pct,
                rule_exp_pct=exp_pct,
                rule_proj_pct=proj_pct,
                critical_missing_count=missing_must_count,
                has_jd_skills=has_jd_criteria,
                total_must_have_count=len(job.must_have_skills or []),
                vector_available=bool(c.embedding or []) and bool(job.embedding or []),
                calibrated_weights=phase_b_weights,
                score_bias_points=phase_b_bias,
                phase_c_enabled=bool(settings.PHASE_C_SCORING_ENABLED),
                ai_confidence=str((ai_scores or {}).get("confidence", "")),
                jd_signal_strength=phase_b_meta.get("jd_signal_strength"),
                required_skills=job.must_have_skills or [],
                work_experience=c.work_experience or [],
                skill_years=skill_years_c,
            )
        )

        ai = ai_scores or {}
        new_breakdown = {
            "ai_score_used":        ai_scores is not None,
            "ai_skill_score":       ai.get("skill_score"),
            "ai_experience_score":  ai.get("experience_score"),
            "ai_project_score":     ai.get("project_score"),
            "matched_must_have":    ai.get("matched_must_have", []),
            "missing_must_have":    ai.get("missing_must_have", []),
            "matched_good_to_have": ai.get("matched_good_to_have", []),
            "reasoning":            ai.get("reasoning", ""),
            "domain_fit":           ai.get("domain_fit", "exact"),
            "seniority_match":      ai.get("seniority_match", "exact"),
            "hire_recommendation":  ai.get("hire_recommendation", "maybe"),
            "red_flags":            ai.get("red_flags", []),
            "standout_factors":     ai.get("standout_factors", []),
            "confidence":           ai.get("confidence", "medium"),
            "rule_based": {
                "skill_pct": round(skill_pct, 1),
                "exp_pct":   round(exp_pct, 1),
                "proj_pct":  round(proj_pct, 1),
            },
            "candidate_tier": scoring_service.detect_candidate_tier(exp_years),
            "from_cache": ai_scores is not None and c.score_breakdown is not None,
            "phase_b_calibration": phase_b_meta,
            "phase_c_applied": bool(settings.PHASE_C_SCORING_ENABLED),
            "jd_hash": _current_jd_hash,
        }

        new_c = Candidate(
            job_id=job.id,
            # Imported pipeline candidates are recruiter-managed records, not
            # candidate self-apply rows. Keep user_id null for job pipeline rows.
            user_id=None,
            name=c.name,
            email=c.email,
            phone=c.phone,
            location=c.location,
            skills=c.skills,
            normalized_skills=c.normalized_skills,
            experience_years=c.experience_years,
            education=c.education,
            projects=c.projects,
            work_experience=c.work_experience,
            skill_years=c.skill_years,
            raw_resume_text=c.raw_resume_text,
            resume_path=c.resume_path,
            file_hash=c.file_hash,
            embedding=c.embedding,
            career_breaks=c.career_breaks,
            skill_match_pct=used_skill_pct,
            experience_match_pct=used_exp_pct,
            project_relevance_pct=used_proj_pct,
            education_match_pct=edu_pct,
            location_match_pct=loc_pct,
            vector_similarity=vec_sim,
            resume_score=final_score,
            final_score=final_score,
            score_breakdown=new_breakdown,
            tag=scoring_service.assign_tag(final_score),
        )
        return new_c

    # BUG 11 FIX: run AI scoring concurrently instead of sequentially
    task_results = await asyncio.gather(
        *[_import_task(cid) for cid in body.candidate_ids],
        return_exceptions=True,
    )
    skipped_unauthorized = [cid for cid in body.candidate_ids if cid in skipped_unauthorized_set]
    imported = 0
    skipped = 0
    errors = 0
    for r in task_results:
        if isinstance(r, Candidate):
            db.add(r)
            imported += 1
        elif isinstance(r, Exception):
            # FIX Finding 10: log exceptions instead of silently counting as skipped
            logger.error("Import task failed: %s", r, exc_info=r)
            errors += 1
        else:
            skipped += 1

    if imported > 0:
        # BUG-14 FIX: flush first so SQLAlchemy assigns DB-side IDs before we log.
        # gen_uuid() runs at __init__ so r.id always exists â€” remove the unnecessary
        # hasattr guard that fell back to logging the pool SOURCE candidate ID.
        await db.flush()
        await recompute_job_rank_and_tags(db, job)
        for cid, r in zip(body.candidate_ids, task_results):
            if isinstance(r, Candidate):
                await log_action(db, user.id, "IMPORT_FROM_POOL", "candidate", r.id)

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        # Fallback to catching the class name if IntegrityError doesn't import cleanly
        if "IntegrityError" in str(type(e)):
            raise HTTPException(
                status_code=409,
                detail="One or more candidates are already imported to this job."
            )
        raise e
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "skipped_unauthorized": skipped_unauthorized,
    }
