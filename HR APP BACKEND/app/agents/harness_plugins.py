from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.adapters.langgraph import LangGraphAdapter
from harness.core.context import AgentContext

from app.agents.graphs import (
    build_career_tools_graph,
    build_full_resume_pipeline_graph,
    build_jd_generation_graph,
    build_quiz_generation_graph,
    build_quiz_with_code_eval_graph,
    build_ranking_pipeline_graph,
    build_resume_scoring_agents_graph,
)
from app.agents.specialized import DeduplicationAgent, NotificationAgent
from app.services import gemini_service, resume_fallback_parser


@dataclass
class _HRAgentResult:
    run_id: str
    output: str = ""
    success: bool = True
    steps: int = 1
    tokens: int = 0
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0
    tool_calls: int = 0
    tool_errors: int = 0
    guardrail_hits: int = 0
    handoff_count: int = 0
    cache_hits: int = 0
    cache_read_tokens: int = 0
    failure_class: str | None = None
    error_message: str | None = None
    output_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "output": self.output,
            "steps": self.steps,
            "tokens": self.tokens,
            "success": self.success,
            "failure_class": self.failure_class,
            "error_message": self.error_message,
            "elapsed_seconds": self.elapsed_seconds,
            "cost_usd": self.cost_usd,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "guardrail_hits": self.guardrail_hits,
            "handoff_count": self.handoff_count,
            "cache_hits": self.cache_hits,
            "cache_read_tokens": self.cache_read_tokens,
            "output_data": self.output_data,
        }


def _parse_task_json(task: str) -> dict[str, Any]:
    try:
        data = json.loads(task or "{}")
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _decode_file_bytes(task_data: dict[str, Any]) -> bytes:
    raw = task_data.get("file_bytes")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)

    raw = task_data.get("content")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)

    for key in ("file_bytes_b64", "content_b64"):
        encoded = task_data.get(key)
        if isinstance(encoded, str) and encoded.strip():
            try:
                return base64.b64decode(encoded)
            except Exception:
                continue

    doc_text = task_data.get("doc_text")
    if isinstance(doc_text, str) and doc_text.strip():
        return doc_text.encode("utf-8", errors="ignore")
    return b""


def _default_parsed_job(task_data: dict[str, Any]) -> dict[str, Any]:
    job = task_data.get("parsed_job") or task_data.get("job") or {}
    if isinstance(job, dict) and job:
        return job

    description = (
        task_data.get("job_description")
        or task_data.get("jd_text")
        or task_data.get("doc_text")
        or ""
    )
    return {
        "title": task_data.get("job_title") or "General Role",
        "role": task_data.get("job_title") or "General Role",
        "description": description,
        "must_have_skills": task_data.get("must_have_skills") or [],
        "good_to_have_skills": task_data.get("good_to_have_skills") or [],
        "experience_min": int(task_data.get("experience_min") or 0),
        "experience_max": int(task_data.get("experience_max") or 5),
        "location": task_data.get("location") or "Remote",
    }


async def _run_graph_with_adapter(
    *,
    run_id: str,
    tenant_id: str,
    agent_type: str,
    raw_task: str,
    workspace_path: Any,
    metadata: dict[str, Any],
    task_data: dict[str, Any],
    graph: Any,
) -> _HRAgentResult:
    started = time.perf_counter()
    workspace = Path(str(workspace_path))
    ctx = AgentContext(
        run_id=run_id,
        tenant_id=tenant_id,
        agent_type=agent_type,
        task=raw_task,
        memory=None,
        workspace_path=workspace,
        max_steps=100,
        max_tokens=500_000,
        timeout_seconds=120.0,
        metadata=metadata or {},
    )

    adapter = LangGraphAdapter(graph)
    async for _ in adapter.run(ctx, task_data):
        pass
    result = await adapter.get_result()

    output_data = (
        result.metadata
        if isinstance(result.metadata, dict)
        else {"result": result.metadata}
    )
    elapsed = max(0.0, time.perf_counter() - started)
    return _HRAgentResult(
        run_id=run_id,
        output=str(result.output or ""),
        success=True,
        steps=int(getattr(result, "steps", 1) or 1),
        elapsed_seconds=elapsed,
        output_data=output_data,
    )


class ResumeParserHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        task_data = {
            **task_data,
            "filename": task_data.get("filename") or "resume.txt",
            "file_bytes": _decode_file_bytes(task_data),
            "parsed_job": _default_parsed_job(task_data),
        }
        graph = build_full_resume_pipeline_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="resume_parser",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class ResumeScorerHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        parsed_job = _default_parsed_job(task_data)
        task_data = {
            **task_data,
            "filename": task_data.get("filename") or "resume.txt",
            "file_bytes": _decode_file_bytes(task_data),
            "job_description": task_data.get("job_description") or parsed_job.get("description") or "",
        }
        graph = build_resume_scoring_agents_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="resume_scorer",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class JDGeneratorHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        graph = build_jd_generation_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="jd_generator",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class JDParserHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        started = time.perf_counter()
        task_data = _parse_task_json(task)
        parsed_job = await gemini_service.parse_jd_from_document(task_data.get("doc_text") or "")
        return _HRAgentResult(
            run_id=run_id,
            output="ok",
            success=True,
            steps=1,
            elapsed_seconds=max(0.0, time.perf_counter() - started),
            output_data={"parsed_job": parsed_job},
        )


class QuizGeneratorHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        graph = build_quiz_generation_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="quiz_generator",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class CodeEvaluatorHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        task_data = {
            "jd_text": task_data.get("jd_text") or "Coding assessment",
            "skills": task_data.get("skills") or ["coding"],
            "easy": int(task_data.get("easy") or 0),
            "medium": int(task_data.get("medium") or 0),
            "hard": int(task_data.get("hard") or 0),
            "answers": task_data.get("answers") or {},
            "problem_statement": task_data.get("problem_statement") or "",
            "user_code": task_data.get("user_code") or "",
            "language": task_data.get("language") or "python",
        }
        graph = build_quiz_with_code_eval_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="code_evaluator",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class CandidateRankerHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        task_data = {
            **task_data,
            "candidates": task_data.get("candidates") or [],
            "jd": task_data.get("jd") or {},
            "use_lyzr": bool(task_data.get("use_lyzr", True)),
            "notify_on_complete": bool(task_data.get("notify_on_complete", False)),
        }
        graph = build_ranking_pipeline_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="candidate_ranker",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class ResumeEnhancerHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        task_data = {
            **task_data,
            "operation": "enhance_resume",
            "resume_text": task_data.get("resume_text") or task_data.get("doc_text") or "",
            "parsed_job": _default_parsed_job(task_data),
            "parsed_resume": resume_fallback_parser.coerce_parsed_resume(
                task_data.get("parsed_resume") if isinstance(task_data.get("parsed_resume"), dict) else None,
                text=task_data.get("resume_text") or task_data.get("doc_text") or "",
            ),
        }
        graph = build_career_tools_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="resume_enhancer",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class ResumeBuilderHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        task_data = {
            **task_data,
            "operation": "build_resume",
            "candidate_data": task_data.get("candidate_data") or {},
            "target_role": task_data.get("target_role") or "",
        }
        graph = build_career_tools_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="resume_builder",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class CoverLetterHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        task_data = _parse_task_json(task)
        resume_text = task_data.get("resume_text") or task_data.get("doc_text") or ""
        task_data = {
            **task_data,
            "operation": "cover_letter",
            "parsed_job": _default_parsed_job(task_data),
            "parsed_resume": resume_fallback_parser.coerce_parsed_resume(
                task_data.get("parsed_resume") if isinstance(task_data.get("parsed_resume"), dict) else None,
                text=resume_text,
            ),
            "candidate_name": task_data.get("candidate_name") or "Candidate",
            "company_name": task_data.get("company_name") or "the company",
        }
        graph = build_career_tools_graph()
        return await _run_graph_with_adapter(
            run_id=run_id,
            tenant_id=tenant_id,
            agent_type="cover_letter",
            raw_task=task,
            workspace_path=workspace_path,
            metadata=metadata or {},
            task_data=task_data,
            graph=graph,
        )


class EmbeddingHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        started = time.perf_counter()
        task_data = _parse_task_json(task)
        text = str(task_data.get("text") or "")
        embedding = await gemini_service.get_embedding(text)
        return _HRAgentResult(
            run_id=run_id,
            output="ok",
            success=True,
            steps=1,
            elapsed_seconds=max(0.0, time.perf_counter() - started),
            output_data={"embedding": embedding},
        )


class NotificationHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        started = time.perf_counter()
        task_data = _parse_task_json(task)
        result = await NotificationAgent()(task_data)
        return _HRAgentResult(
            run_id=run_id,
            output="ok",
            success=True,
            steps=1,
            elapsed_seconds=max(0.0, time.perf_counter() - started),
            output_data=result if isinstance(result, dict) else {"result": result},
        )


class DeduplicationHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        started = time.perf_counter()
        task_data = _parse_task_json(task)
        content = _decode_file_bytes(task_data)
        result = await DeduplicationAgent()({**task_data, "content": content})
        return _HRAgentResult(
            run_id=run_id,
            output="ok",
            success=True,
            steps=1,
            elapsed_seconds=max(0.0, time.perf_counter() - started),
            output_data=result if isinstance(result, dict) else {"result": result},
        )


class CareerAnalystHRAgent:
    async def run(
        self,
        tenant_id: str,
        task: str,
        run_id: str,
        workspace_path: Any,
        metadata: dict,
    ) -> _HRAgentResult:
        started = time.perf_counter()
        task_data = _parse_task_json(task)
        resume_text = str(task_data.get("resume_text") or task_data.get("doc_text") or "")
        parsed = resume_fallback_parser.coerce_parsed_resume(None, text=resume_text)
        analysis = await gemini_service.analyze_career_path(
            candidate_name=task_data.get("candidate_name") or parsed.get("name") or "Candidate",
            exp_years=float(parsed.get("experience_years") or task_data.get("experience_years") or 0.0),
            skills=parsed.get("normalized_skills") or parsed.get("skills") or [],
            work_history=parsed.get("work_experience") or [],
            education=parsed.get("education") or [],
            career_breaks=parsed.get("career_breaks") or [],
            target_role=str(task_data.get("target_role") or ""),
        )
        return _HRAgentResult(
            run_id=run_id,
            output="ok",
            success=True,
            steps=1,
            elapsed_seconds=max(0.0, time.perf_counter() - started),
            output_data={"career_analysis": analysis},
        )


_HR_AGENT_FACTORY: dict[str, type] = {
    "resume_parser": ResumeParserHRAgent,
    "resume_scorer": ResumeScorerHRAgent,
    "jd_generator": JDGeneratorHRAgent,
    "jd_parser": JDParserHRAgent,
    "quiz_generator": QuizGeneratorHRAgent,
    "code_evaluator": CodeEvaluatorHRAgent,
    "candidate_ranker": CandidateRankerHRAgent,
    "resume_enhancer": ResumeEnhancerHRAgent,
    "resume_builder": ResumeBuilderHRAgent,
    "cover_letter": CoverLetterHRAgent,
    "embedding": EmbeddingHRAgent,
    "notification": NotificationHRAgent,
    "deduplication": DeduplicationHRAgent,
    "career_analyst": CareerAnalystHRAgent,
}


def build_hr_agent(agent_type: str):
    cls = _HR_AGENT_FACTORY.get(agent_type)
    if cls is None:
        raise ValueError(f"Unknown HR agent type: {agent_type!r}")
    return cls()
