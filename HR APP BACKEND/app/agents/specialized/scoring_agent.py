"""
ScoringAgent — hybrid rule-based + AI resume scoring against a JD.

Wraps the full scoring pipeline from scoring_service and gemini_service:
  1. Rule-based component scores (skill, experience, project, education, location, vector)
  2. Optional AI override via gemini_service.score_resume_against_jd()
  3. Final blended score via compute_resume_score_with_ai_override()
"""
from __future__ import annotations
from typing import Any
from types import SimpleNamespace
import asyncio
import hashlib
import logging
import math
import time

from app.agents.base import BaseAgent
from app.config import settings
from app.services import scoring_service, gemini_service

logger = logging.getLogger(__name__)


_SECTION_EMBED_TTL_SECONDS = 900.0
_SECTION_EMBED_MAX_ITEMS = 2048
_SECTION_EMBED_CACHE: dict[str, tuple[float, list[float]]] = {}
_SECTION_EMBED_CACHE_LOCK = asyncio.Lock()
_SECTION_EMBED_IN_FLIGHT: dict[str, asyncio.Task] = {}


def _section_embed_key(text: str) -> str:
    normalized = " ".join((text or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def _get_cached_embedding(text: str) -> list[float]:
    if not text:
        return []
    key = _section_embed_key(text)
    owner = False
    async with _SECTION_EMBED_CACHE_LOCK:
        now = time.time()
        cached = _SECTION_EMBED_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]

        in_flight = _SECTION_EMBED_IN_FLIGHT.get(key)
        if in_flight is None:
            in_flight = asyncio.create_task(gemini_service.get_embedding(text))
            _SECTION_EMBED_IN_FLIGHT[key] = in_flight
            owner = True

    try:
        vec = await in_flight
    except Exception:
        if owner:
            async with _SECTION_EMBED_CACHE_LOCK:
                if _SECTION_EMBED_IN_FLIGHT.get(key) is in_flight:
                    _SECTION_EMBED_IN_FLIGHT.pop(key, None)
        raise

    if not isinstance(vec, list):
        vec = []

    if owner:
        async with _SECTION_EMBED_CACHE_LOCK:
            now = time.time()
            expiry = now + _SECTION_EMBED_TTL_SECONDS
            _SECTION_EMBED_CACHE[key] = (expiry, vec)
            # Opportunistic cleanup: remove expired entries first, then hard-cap size.
            stale_keys = [k for k, (exp, _) in _SECTION_EMBED_CACHE.items() if exp <= now]
            for stale in stale_keys:
                _SECTION_EMBED_CACHE.pop(stale, None)
            while len(_SECTION_EMBED_CACHE) > _SECTION_EMBED_MAX_ITEMS:
                oldest_key = next(iter(_SECTION_EMBED_CACHE))
                _SECTION_EMBED_CACHE.pop(oldest_key, None)
            if _SECTION_EMBED_IN_FLIGHT.get(key) is in_flight:
                _SECTION_EMBED_IN_FLIGHT.pop(key, None)

    return vec


class ScoringAgent(BaseAgent):
    name = "scoring_agent"
    model_key = "scoring_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        parsed_resume: dict = state.get("parsed_resume") or {}
        parsed_job: dict = state.get("parsed_job") or {}
        embedding: list = state.get("embedding") or []

        if not parsed_resume:
            raise ValueError("ScoringAgent: 'parsed_resume' is required in state")
        if not parsed_job:
            raise ValueError("ScoringAgent: 'parsed_job' is required in state")

        # Build a lightweight JD namespace (same shape as the ORM model)
        def _safe_int(v, default): 
            try: return int(v)
            except (TypeError, ValueError):
                return default

        def _ensure_list(v):
            if isinstance(v, list): return v
            if isinstance(v, str): return [s.strip() for s in v.split(",") if s.strip()]
            return []

        experience_min = max(0, _safe_int(parsed_job.get("experience_min"), 0))
        experience_max = max(0, _safe_int(parsed_job.get("experience_max"), max(experience_min + 3, experience_min + 1)))
        if experience_max <= experience_min:
            corrected_max = max(experience_min + 3, experience_min + 1)
            logger.info(
                "Corrected inverted experience range: min=%s -> max=%s",
                experience_min,
                corrected_max,
            )
            experience_max = corrected_max

        job = SimpleNamespace(
            id=parsed_job.get("id") or "agent_jd",
            title=parsed_job.get("title") or parsed_job.get("role") or "Role",
            role=parsed_job.get("role") or parsed_job.get("title") or "Role",
            experience_min=experience_min,
            experience_max=experience_max,
            must_have_skills=_ensure_list(parsed_job.get("must_have_skills")),
            good_to_have_skills=_ensure_list(parsed_job.get("good_to_have_skills")),
            description=parsed_job.get("description") or "",
            education_requirement=parsed_job.get("education_requirement"),
            location=parsed_job.get("location"),
            embedding=state.get("jd_embedding") or [],
        )

        normalized_skills = parsed_resume.get("normalized_skills") or []
        try:
            exp_years = float(parsed_resume.get("experience_years") or 0.0)
        except (TypeError, ValueError):
            exp_years = 0.0
        if not math.isfinite(exp_years) or exp_years < 0:
            exp_years = 0.0
        skill_yrs = parsed_resume.get("skill_years") or {}
        projects = parsed_resume.get("projects") or []
        education = parsed_resume.get("education") or []
        location = parsed_resume.get("location")
        work_experience = parsed_resume.get("work_experience") or []

        # Component scores
        rule_skill = scoring_service.skill_match_score(normalized_skills, job.must_have_skills, job.good_to_have_skills)
        rule_exp = scoring_service.experience_match_score(exp_years, job.experience_min, job.experience_max, skill_yrs, job.must_have_skills)
        rule_proj = scoring_service.project_relevance_score(projects, job.must_have_skills, job.good_to_have_skills, exp_years)
        edu_pct = scoring_service.education_match_score(education, experience_years=exp_years,
                    jd_description=job.description, jd_must_have=job.must_have_skills,
                    jd_education_requirement=job.education_requirement)
        loc_pct = scoring_service.location_match_score(location, job.location)
        vector_warnings: list[dict[str, str]] = []
        try:
            full_vec_sim = scoring_service.cosine_similarity(embedding, job.embedding)
        except ValueError as vec_err:
            logger.warning("ScoringAgent full-vector similarity degraded: %s", vec_err)
            full_vec_sim = 0.0
            vector_warnings.append(
                {"stage": "full_similarity", "type": "dimension_mismatch", "detail": str(vec_err)}
            )
        vector_available = bool(embedding) and bool(job.embedding)

        # Section-level vector benchmark:
        # skills-vs-requirements and experience-vs-responsibilities.
        skills_vec_sim: float | None = None
        experience_vec_sim: float | None = None
        if not state.get("skip_ai_scoring", False):
            resume_skills_text = ", ".join([str(s).strip() for s in (normalized_skills or parsed_resume.get("skills") or []) if str(s).strip()])
            jd_skills_text = ", ".join([str(s).strip() for s in ((job.must_have_skills or []) + (job.good_to_have_skills or [])) if str(s).strip()])

            exp_chunks: list[str] = []
            for row in work_experience:
                if not isinstance(row, dict):
                    continue
                role = str(row.get("role") or "").strip()
                company = str(row.get("company") or "").strip()
                summary = str(row.get("summary") or row.get("description") or "").strip()
                skills_txt = ", ".join([str(s).strip() for s in (row.get("skills") or []) if str(s).strip()])
                chunk = " | ".join([x for x in [role, company, summary, skills_txt] if x])
                if chunk:
                    exp_chunks.append(chunk)
            if not exp_chunks and projects:
                exp_chunks = [str(p).strip() for p in projects if str(p).strip()]
            resume_experience_text = "\n".join(exp_chunks)[:6000]

            jd_responsibilities_text = "\n".join([
                str(job.description or "").strip(),
                f"Experience range: {job.experience_min}-{job.experience_max} years",
            ]).strip()[:6000]

            async def _pair_similarity(left: str, right: str) -> float | None:
                if not left or not right:
                    return None
                try:
                    left_vec, right_vec = await asyncio.wait_for(
                        asyncio.gather(
                            _get_cached_embedding(left),
                            _get_cached_embedding(right),
                        ),
                        timeout=max(8.0, min(25.0, float(state.get("timeout_s", 45.0)) * 0.6)),
                    )
                    try:
                        sim = scoring_service.cosine_similarity(left_vec or [], right_vec or [])
                    except ValueError as vec_err:
                        logger.warning("ScoringAgent section similarity degraded: %s", vec_err)
                        vector_warnings.append(
                            {"stage": "section_similarity", "type": "dimension_mismatch", "detail": str(vec_err)}
                        )
                        return 0.0
                    return float(sim)
                except Exception as sec_err:
                    logger.debug("ScoringAgent section embedding failed: %s", sec_err)
                    return None

            skills_vec_sim, experience_vec_sim = await asyncio.gather(
                _pair_similarity(resume_skills_text, jd_skills_text),
                _pair_similarity(resume_experience_text, jd_responsibilities_text),
            )
        composite_vec_sim, vector_meta = scoring_service.compute_composite_vector_similarity(
            full_similarity=full_vec_sim,
            skills_similarity=skills_vec_sim,
            experience_similarity=experience_vec_sim,
        )

        critical_missing = sum(
            1 for s in job.must_have_skills
            if not scoring_service.semantic_skill_match(s, normalized_skills)
        )

        # AI scoring (optional — degrades gracefully)
        ai_scores: dict | None = None
        skip_ai = state.get("skip_ai_scoring", False)
        if not skip_ai:
            model = self.resolve_model(state)
            try:
                ai_scores = await asyncio.wait_for(
                    gemini_service.score_resume_against_jd(
                        parsed_resume=parsed_resume,
                        job_title=job.title,
                        exp_min=job.experience_min, exp_max=job.experience_max,
                        must_have=job.must_have_skills, good_to_have=job.good_to_have_skills,
                        description=job.description,
                        model=model,
                    ),
                    timeout=max(5.0, float(state.get("timeout_s", 45))),
                )
            except Exception as ai_err:
                logger.warning("ScoringAgent: AI scoring failed, using rule-based fallback: %s", ai_err)

        has_jd_criteria = bool(
            job.must_have_skills
            or job.good_to_have_skills
            or (job.description or "").strip()
            or getattr(job, "education_requirement", None)
        )
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

        resume_score, used_skill, used_exp, used_proj = scoring_service.compute_resume_score_with_ai_override(
            ai_scores=ai_scores,
            education_pct=edu_pct, vector_sim=composite_vec_sim, location_pct=loc_pct,
            experience_years=exp_years,
            rule_skill_pct=rule_skill, rule_exp_pct=rule_exp, rule_proj_pct=rule_proj,
            critical_missing_count=critical_missing,
            has_jd_skills=has_jd_criteria,
            total_must_have_count=len(job.must_have_skills or []),
            vector_available=vector_available,
            calibrated_weights=phase_b_weights,
            score_bias_points=phase_b_bias,
            phase_c_enabled=bool(settings.PHASE_C_SCORING_ENABLED),
            ai_confidence=str((ai_scores or {}).get("confidence", "")),
            jd_signal_strength=phase_b_meta.get("jd_signal_strength"),
            required_skills=list(job.must_have_skills or []),
            work_experience=work_experience,
            skill_years=skill_yrs,
            skills_vector_similarity=skills_vec_sim,
            experience_vector_similarity=experience_vec_sim,
        )

        tag = scoring_service.assign_tag(resume_score)
        ai = ai_scores if isinstance(ai_scores, dict) else {}
        ai_score_used = bool(
            ai_scores
            and not bool(ai.get("parse_failed", False))
            and isinstance(ai.get("overall"), (int, float))
        )

        def _as_list(value: Any) -> list[Any]:
            return value if isinstance(value, list) else []

        score_result = {
            "resume_score": resume_score,
            "tag": tag.value if hasattr(tag, "value") else str(tag),
            "ai_score_used": ai_score_used,
            "skill_match_pct": round(used_skill, 1),
            "experience_match_pct": round(used_exp, 1),
            "project_relevance_pct": round(used_proj, 1),
            "education_match_pct": round(edu_pct, 1),
            "location_match_pct": round(loc_pct, 1),
            "vector_similarity": round(composite_vec_sim, 4),
            "vector_similarity_full": round(full_vec_sim, 4),
            "vector_similarity_skills": round(float(skills_vec_sim), 4) if skills_vec_sim is not None else None,
            "vector_similarity_experience": round(float(experience_vec_sim), 4) if experience_vec_sim is not None else None,
            "vector_components": vector_meta.get("components", {}),
            "vector_warning": bool(vector_warnings),
            "vector_warning_details": vector_warnings,
            "matched_must_have": _as_list(ai.get("matched_must_have")),
            "missing_must_have": _as_list(ai.get("missing_must_have")),
            "matched_good_to_have": _as_list(ai.get("matched_good_to_have")),
            "missing_good_to_have": _as_list(ai.get("missing_good_to_have")),
            "reasoning": ai.get("reasoning", ""),
            "domain_fit": ai.get("domain_fit", "exact"),
            "seniority_match": ai.get("seniority_match", "exact"),
            "hire_recommendation": ai.get("hire_recommendation", "maybe"),
            "red_flags": _as_list(ai.get("red_flags")),
            "standout_factors": _as_list(ai.get("standout_factors")),
            "confidence": ai.get("confidence", "medium"),
            "candidate_tier": scoring_service.detect_candidate_tier(exp_years),
            "phase_b_calibration": phase_b_meta,
            "phase_c_applied": bool(settings.PHASE_C_SCORING_ENABLED),
        }

        return {"score_result": score_result}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded",
                "note": "AI scoring unavailable — rule-based fallback active" if not ok else None}
