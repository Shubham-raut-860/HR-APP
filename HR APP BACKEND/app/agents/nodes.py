"""LangGraph node wrappers around existing service functions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.agents.state import (
    CandidateToolsState,
    JDGenerationState,
    QuizGenerationState,
    ResumeAgentState,
    ResumeScreeningState,
)
from app.config import settings
from app.services import cache_service, file_service, gemini_service, scoring_service


def _resolve_model(state: dict, key: str) -> str:
    override = state.get("model_override")
    if isinstance(override, str) and override.strip():
        return override.strip()
    keyed = state.get("model_overrides")
    if isinstance(keyed, dict):
        keyed_override = keyed.get(key)
        if isinstance(keyed_override, str) and keyed_override.strip():
            return keyed_override.strip()
    return settings.agent_model_map.get(key) or settings.AZURE_CHAT_DEPLOYMENT


async def extract_resume_text(state: ResumeScreeningState) -> ResumeScreeningState:
    text = await file_service.extract_text_from_bytes(
        state["filename"],
        state["content"],
    )
    return {"text": text}


async def compute_resume_data(state: ResumeScreeningState) -> ResumeScreeningState:
    # Reuse the existing router helper to preserve the current scoring behavior
    # exactly while exposing it as an agent node.
    from app.routers.resumes import _compute_resume_data_from_bytes

    resume_data = await _compute_resume_data_from_bytes(
        state["filename"],
        state["content"],
        state["text"],
        state["job"],
        cached_candidate=state.get("cached_candidate"),
        user_email=state.get("user_email"),
    )
    return {"resume_data": resume_data}


async def document_intake_agent(state: ResumeAgentState) -> ResumeAgentState:
    filename = state.get("filename") or "resume.pdf"
    resume_text = await file_service.extract_text_from_bytes(filename, state["file_bytes"])
    result: ResumeAgentState = {"resume_text": resume_text}
    if "resume_text" not in result or result["resume_text"] is None:
        raise ValueError("document_intake_agent missing required key: resume_text")
    return result


async def resume_parser_agent(state: ResumeAgentState) -> ResumeAgentState:
    resume_model = _resolve_model(state, "resume_parser_agent")
    jd_model = _resolve_model(state, "jd_parser_agent")
    parsed_resume, parsed_job = await asyncio.gather(
        gemini_service.parse_resume(state["resume_text"], model=resume_model),
        gemini_service.parse_jd_from_document(state["job_description"], model=jd_model),
    )
    result: ResumeAgentState = {"parsed_resume": parsed_resume, "parsed_job": parsed_job}
    if "parsed_resume" not in result or result["parsed_resume"] is None:
        raise ValueError("resume_parser_agent missing required key: parsed_resume")
    if "parsed_job" not in result or result["parsed_job"] is None:
        raise ValueError("resume_parser_agent missing required key: parsed_job")
    return result


async def scoring_agent(state: ResumeAgentState) -> ResumeAgentState:
    from app.routers.resumes import _compute_resume_data_from_bytes

    def safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def ensure_list(value):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return []

    parsed_job = state.get("parsed_job") or {}
    job_description = state.get("job_description") or parsed_job.get("description") or ""
    filename = state.get("filename") or "resume.pdf"

    job = SimpleNamespace(
        id=parsed_job.get("id") or "agent_jd",
        title=parsed_job.get("title") or parsed_job.get("role") or "Generated JD",
        experience_min=safe_int(parsed_job.get("experience_min"), 0),
        experience_max=safe_int(parsed_job.get("experience_max"), 5),
        must_have_skills=ensure_list(parsed_job.get("must_have_skills")),
        good_to_have_skills=ensure_list(parsed_job.get("good_to_have_skills")),
        description=job_description,
        education_requirement=parsed_job.get("education_requirement"),
        location=parsed_job.get("location"),
        embedding=[],
    )

    score_result = await _compute_resume_data_from_bytes(
        filename,
        state["file_bytes"],
        state.get("resume_text") or "",
        job,
        pre_parsed_data=state.get("parsed_resume"),
    )
    result: ResumeAgentState = {"score_result": score_result}
    if "score_result" not in result or result["score_result"] is None:
        raise ValueError("scoring_agent missing required key: score_result")
    return result


async def build_jd_cache_query(state: JDGenerationState) -> JDGenerationState:
    cache_query = (
        f"Role: {state['role']} "
        f"Exp: {state.get('experience_min', 0)}-{state.get('experience_max', 5)} "
        f"Loc: {state.get('location')} "
        f"Ctx: {state.get('additional_context')}"
    )
    return {"cache_query": cache_query}


async def embed_jd_query(state: JDGenerationState) -> JDGenerationState:
    embedding = await gemini_service.get_embedding(state["cache_query"])
    return {"query_embedding": embedding}


async def read_jd_cache(state: JDGenerationState) -> JDGenerationState:
    cached = cache_service.get_cached_jd(state["query_embedding"])
    if cached:
        return {"jd_data": cached, "cache_hit": True}
    return {"cache_hit": False}


def route_jd_cache(state: JDGenerationState) -> str:
    return "cached" if state.get("cache_hit") else "generate"


async def generate_jd_data(state: JDGenerationState) -> JDGenerationState:
    model = _resolve_model(state, "jd_generator_agent")
    jd_data = await gemini_service.generate_jd(
        role=state["role"],
        exp_min=state.get("experience_min", 0),
        exp_max=state.get("experience_max", 5),
        location=state.get("location") or "Remote",
        context=state.get("additional_context") or "",
        model=model,
    )
    return {"jd_data": jd_data}


async def write_jd_cache(state: JDGenerationState) -> JDGenerationState:
    cache_service.cache_jd(state["query_embedding"], state["jd_data"])
    return {}


async def generate_quiz_data(state: QuizGenerationState) -> QuizGenerationState:
    model = _resolve_model(state, "quiz_agent_generate")
    questions = await gemini_service.generate_quiz_questions(
        jd_text=state["jd_text"],
        skills=state.get("skills", []),
        easy=state.get("easy", 8),
        medium=state.get("medium", 8),
        hard=state.get("hard", 4),
        model=model,
    )
    return {"questions": questions}


async def enhance_resume(state: CandidateToolsState) -> CandidateToolsState:
    job = state["job"]
    model = _resolve_model(state, "resume_enhancer_agent")
    result = await gemini_service.enhance_resume(
        resume_text=state["resume_text"],
        job_title=job.title,
        must_have=job.must_have_skills or [],
        good_to_have=job.good_to_have_skills or [],
        job_description=job.description or "",
        current_score=state.get("current_score", 0.0),
        missing_skills=state.get("missing_skills", []),
        model=model,
    )
    return {"result": result}


async def build_resume(state: CandidateToolsState) -> CandidateToolsState:
    model = _resolve_model(state, "resume_builder_agent")
    result = await gemini_service.build_resume_from_form(
        candidate_data=state.get("candidate_data", {}),
        target_role=state.get("target_role", ""),
        model=model,
    )
    return {"result": result}


def route_candidate_tool(state: CandidateToolsState) -> str:
    operation = state.get("operation")
    if operation == "enhance_resume":
        return "enhance_resume"
    if operation == "build_resume":
        return "build_resume"
    raise ValueError(f"Unsupported candidate tool operation: {operation}")


def compute_skill_gaps(resume_skills: list[str], job: object) -> list[str]:
    return [
        skill
        for skill in (getattr(job, "must_have_skills", None) or [])
        if not scoring_service.semantic_skill_match(skill, resume_skills)
    ]
