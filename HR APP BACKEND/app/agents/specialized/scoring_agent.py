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
import logging

from app.agents.base import BaseAgent
from app.services import scoring_service, gemini_service

logger = logging.getLogger(__name__)


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
            except: return default

        def _ensure_list(v):
            if isinstance(v, list): return v
            if isinstance(v, str): return [s.strip() for s in v.split(",") if s.strip()]
            return []

        job = SimpleNamespace(
            id=parsed_job.get("id") or "agent_jd",
            title=parsed_job.get("title") or parsed_job.get("role") or "Role",
            experience_min=_safe_int(parsed_job.get("experience_min"), 0),
            experience_max=_safe_int(parsed_job.get("experience_max"), 5),
            must_have_skills=_ensure_list(parsed_job.get("must_have_skills")),
            good_to_have_skills=_ensure_list(parsed_job.get("good_to_have_skills")),
            description=parsed_job.get("description") or "",
            education_requirement=parsed_job.get("education_requirement"),
            location=parsed_job.get("location"),
            embedding=state.get("jd_embedding") or [],
        )

        normalized_skills = parsed_resume.get("normalized_skills") or []
        exp_years = float(parsed_resume.get("experience_years") or 0.0)
        skill_yrs = parsed_resume.get("skill_years") or {}
        projects = parsed_resume.get("projects") or []
        education = parsed_resume.get("education") or []
        location = parsed_resume.get("location")

        # Component scores
        rule_skill = scoring_service.skill_match_score(normalized_skills, job.must_have_skills, job.good_to_have_skills)
        rule_exp = scoring_service.experience_match_score(exp_years, job.experience_min, job.experience_max, skill_yrs, job.must_have_skills)
        rule_proj = scoring_service.project_relevance_score(projects, job.must_have_skills, job.good_to_have_skills, exp_years)
        edu_pct = scoring_service.education_match_score(education, experience_years=exp_years,
                    jd_description=job.description, jd_must_have=job.must_have_skills,
                    jd_education_requirement=job.education_requirement)
        loc_pct = scoring_service.location_match_score(location, job.location)
        vec_sim = scoring_service.cosine_similarity(embedding, job.embedding)

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

        resume_score, used_skill, used_exp, used_proj = scoring_service.compute_resume_score_with_ai_override(
            ai_scores=ai_scores,
            education_pct=edu_pct, vector_sim=vec_sim, location_pct=loc_pct,
            experience_years=exp_years,
            rule_skill_pct=rule_skill, rule_exp_pct=rule_exp, rule_proj_pct=rule_proj,
            critical_missing_count=critical_missing,
            has_jd_skills=has_jd_criteria,
        )

        tag = scoring_service.assign_tag(resume_score)
        ai = ai_scores or {}

        score_result = {
            "resume_score": resume_score,
            "tag": tag.value if hasattr(tag, "value") else str(tag),
            "ai_score_used": ai_scores is not None,
            "skill_match_pct": round(used_skill, 1),
            "experience_match_pct": round(used_exp, 1),
            "project_relevance_pct": round(used_proj, 1),
            "education_match_pct": round(edu_pct, 1),
            "location_match_pct": round(loc_pct, 1),
            "vector_similarity": round(vec_sim, 4),
            "matched_must_have": ai.get("matched_must_have", []),
            "missing_must_have": ai.get("missing_must_have", []),
            "matched_good_to_have": ai.get("matched_good_to_have", []),
            "missing_good_to_have": ai.get("missing_good_to_have", []),
            "reasoning": ai.get("reasoning", ""),
            "domain_fit": ai.get("domain_fit", "exact"),
            "seniority_match": ai.get("seniority_match", "exact"),
            "hire_recommendation": ai.get("hire_recommendation", "maybe"),
            "red_flags": ai.get("red_flags", []),
            "standout_factors": ai.get("standout_factors", []),
            "confidence": ai.get("confidence", "medium"),
            "candidate_tier": scoring_service.detect_candidate_tier(exp_years),
        }

        return {"score_result": score_result}

    async def health(self) -> dict[str, Any]:
        ok = bool(gemini_service.openai_client)
        return {"agent": self.name, "status": "ok" if ok else "degraded",
                "note": "AI scoring unavailable — rule-based fallback active" if not ok else None}
