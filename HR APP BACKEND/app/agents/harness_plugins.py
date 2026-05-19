from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from harness.agents.base import BaseAgent as _HarnessBaseAgent
except Exception:  # pragma: no cover - keeps runtime fallback working when harness import is unavailable
    class _HarnessBaseAgent:  # type: ignore[too-many-ancestors]
        pass

try:
    from harness.observability.trace_schema import SpanKind, SpanStatus
except Exception:  # pragma: no cover
    SpanKind = SpanStatus = None  # type: ignore[assignment]

from app.agents.specialized import (
    CareerAnalystAgent,
    CodeEvaluationAgent,
    DeduplicationAgent,
    CoverLetterAgent,
    EmbeddingAgent,
    FileExtractionAgent,
    JDGeneratorAgent,
    JDParserAgent,
    NotificationAgent,
    QuizAgent,
    RankingAgent,
    ResumeBuilderAgent,
    ResumeEnhancerAgent,
    ResumeParserAgent,
    ScoringAgent,
)
from app.services.token_monitor_service import get_token_monitor

logger = logging.getLogger(__name__)


def _ensure_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ensure_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _parse_task(task: str) -> dict[str, Any]:
    if not task:
        return {}
    try:
        parsed = json.loads(task)
    except json.JSONDecodeError:
        return {"raw_task": task}
    return parsed if isinstance(parsed, dict) else {"task_payload": parsed}


def _build_parsed_job(task_data: dict[str, Any]) -> dict[str, Any]:
    parsed = task_data.get("parsed_job")
    if isinstance(parsed, dict) and parsed:
        return parsed
    return {
        "title": task_data.get("job_title") or task_data.get("title") or task_data.get("role") or "Role",
        "role": task_data.get("role") or task_data.get("job_title") or task_data.get("title") or "Role",
        "experience_min": _ensure_int(task_data.get("exp_min", task_data.get("experience_min")), 0),
        "experience_max": _ensure_int(task_data.get("exp_max", task_data.get("experience_max")), 5),
        "must_have_skills": _ensure_list(task_data.get("must_have")),
        "good_to_have_skills": _ensure_list(task_data.get("good_to_have")),
        "description": str(task_data.get("description") or ""),
        "location": task_data.get("location") or "Remote",
        "education_requirement": task_data.get("education_requirement"),
    }


def _decode_file_bytes(task_data: dict[str, Any]) -> bytes | None:
    raw = task_data.get("content_b64") or task_data.get("file_bytes_b64")
    if not raw:
        return None
    if not isinstance(raw, str):
        return None
    try:
        return base64.b64decode(raw)
    except Exception:
        return None


def _safe_preview(value: Any, limit: int = 500) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text


@dataclass
class _HRAgentResult:
    run_id: str
    success: bool = True
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    steps: int = 1
    tokens: int = 0
    failure_class: str | None = None
    error_message: str | None = None
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0
    tool_calls: int = 0
    tool_errors: int = 0
    guardrail_hits: int = 0
    handoff_count: int = 0
    cache_hits: int = 0
    cache_read_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
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
            "metadata": self.metadata,
            "data": self.data,
        }
        if self.data:
            payload.update(self.data)
        return payload


@dataclass
class _HarnessStepEvent:
    run_id: str
    step: int
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class _LocalRunCtx:
    run_id: str
    tenant_id: str
    agent_type: str
    task: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    step_count: int = 0
    token_count: int = 0
    failure_class: str | None = None
    failed: bool = False

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(UTC) - self.started_at).total_seconds()


class _HRHarnessAgentBase(_HarnessBaseAgent):
    agent_type = "base"

    def __init__(self, *_args: Any, **kwargs: Any) -> None:
        # Accept arbitrary kwargs so this class can also be instantiated by
        # harness.workers.agent_worker plugin path (which passes common kwargs).
        self._trace_recorder = kwargs.get("trace_recorder")
        self._event_bus = kwargs.get("event_bus")
        self._mlflow_tracer = kwargs.get("mlflow_tracer")

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def _emit_event(self, event: _HarnessStepEvent) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(event)
        except Exception as exc:
            logger.debug("HR harness event publish skipped: %s", exc)

    async def run(
        self,
        ctx: Any = None,
        *,
        tenant_id: str | None = None,
        task: str | None = None,
        run_id: str | None = None,
        workspace_path: Any = None,  # noqa: ARG002
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> _HRAgentResult:
        del metadata

        if ctx is not None and hasattr(ctx, "task") and hasattr(ctx, "run_id"):
            raw_task = str(getattr(ctx, "task") or "")
            resolved_run_id = str(getattr(ctx, "run_id") or run_id or "")
            run_ctx: Any = ctx
        else:
            raw_task = str(task or "")
            resolved_run_id = str(run_id or "")
            run_ctx = _LocalRunCtx(
                run_id=resolved_run_id,
                tenant_id=str(tenant_id or "default"),
                agent_type=self.agent_type,
                task=raw_task,
            )

        task_data = _parse_task(raw_task)
        trace_run_span_id: str | None = None
        trace_exec_span_id: str | None = None
        token_monitor = get_token_monitor()
        token_checkpoint = token_monitor.checkpoint() if token_monitor.enabled else None
        started = time.perf_counter()

        await self._emit_event(
            _HarnessStepEvent(
                run_id=resolved_run_id,
                step=int(getattr(run_ctx, "step_count", 0) or 0),
                event_type="started",
                payload={"task": raw_task, "agent_type": self.agent_type},
            )
        )
        if (
            self._trace_recorder is not None
            and SpanKind is not None
            and SpanStatus is not None
        ):
            try:
                trace_run_span_id = await self._trace_recorder.start_span(
                    resolved_run_id,
                    SpanKind.RUN,  # type: ignore[arg-type]
                    f"run:{self.agent_type}",
                    ctx=run_ctx,
                    input_preview=raw_task[:500],
                    metadata={"plugin": "hr_app"},
                )
                trace_exec_span_id = await self._trace_recorder.start_span(
                    resolved_run_id,
                    SpanKind.AGENT,  # type: ignore[arg-type]
                    f"agent:{self.agent_type}",
                    ctx=run_ctx,
                    input_preview=_safe_preview(task_data),
                )
            except Exception as exc:
                logger.debug("HR trace start skipped: %s", exc)
                trace_run_span_id = None
                trace_exec_span_id = None

        try:
            output_data = await self._execute(task_data)
            output_text = ""
            if isinstance(output_data, dict):
                output_text = str(
                    output_data.get("summary")
                    or output_data.get("reasoning")
                    or output_data.get("output")
                    or ""
                )
            if hasattr(run_ctx, "step_count"):
                run_ctx.step_count = int(getattr(run_ctx, "step_count", 0) or 0) + 1

            token_delta = (
                token_monitor.delta_since(token_checkpoint)
                if token_checkpoint is not None
                else {}
            )
            tokens_used = int(token_delta.get("total_tokens", 0) or 0)
            cost_used = float(token_delta.get("total_cost_usd", 0.0) or 0.0)
            if hasattr(run_ctx, "token_count"):
                run_ctx.token_count = int(getattr(run_ctx, "token_count", 0) or 0) + tokens_used

            if (
                self._trace_recorder is not None
                and trace_exec_span_id is not None
                and SpanStatus is not None
            ):
                try:
                    await self._trace_recorder.end_span(
                        resolved_run_id,
                        trace_exec_span_id,
                        status=SpanStatus.OK,  # type: ignore[arg-type]
                        output_preview=_safe_preview(output_data),
                        input_tokens=tokens_used,
                        output_tokens=0,
                        cost_usd=cost_used,
                    )
                except Exception as exc:
                    logger.debug("HR trace execute end skipped: %s", exc)

            await self._emit_event(
                _HarnessStepEvent(
                    run_id=resolved_run_id,
                    step=int(getattr(run_ctx, "step_count", 0) or 0),
                    event_type="completed",
                    payload={"output": output_text, "elapsed_seconds": getattr(run_ctx, "elapsed_seconds", 0.0)},
                )
            )
            return _HRAgentResult(
                run_id=resolved_run_id,
                success=True,
                output=output_text,
                data=output_data if isinstance(output_data, dict) else {"result": output_data},
                steps=int(getattr(run_ctx, "step_count", 1) or 1),
                tokens=tokens_used,
                elapsed_seconds=float(time.perf_counter() - started),
                cost_usd=cost_used,
                metadata={
                    "agent_type": self.agent_type,
                    "trace_enabled": bool(self._trace_recorder is not None),
                    "token_calls": int(token_delta.get("calls", 0) or 0),
                    "token_prompt": int(token_delta.get("prompt_tokens", 0) or 0),
                    "token_completion": int(token_delta.get("completion_tokens", 0) or 0),
                    "token_over_budget_calls": int(token_delta.get("over_budget_calls", 0) or 0),
                },
            )
        except Exception as exc:
            if hasattr(run_ctx, "failed"):
                run_ctx.failed = True
            if hasattr(run_ctx, "failure_class"):
                run_ctx.failure_class = "runtime_error"
            if (
                self._trace_recorder is not None
                and trace_exec_span_id is not None
                and SpanStatus is not None
            ):
                try:
                    await self._trace_recorder.end_span(
                        resolved_run_id,
                        trace_exec_span_id,
                        status=SpanStatus.ERROR,  # type: ignore[arg-type]
                        error=str(exc),
                        output_preview="failed",
                    )
                except Exception as end_exc:
                    logger.debug("HR trace execute error end skipped: %s", end_exc)
            await self._emit_event(
                _HarnessStepEvent(
                    run_id=resolved_run_id,
                    step=int(getattr(run_ctx, "step_count", 0) or 0),
                    event_type="failed",
                    payload={
                        "error": str(exc),
                        "failure_class": getattr(run_ctx, "failure_class", None),
                        "elapsed_seconds": getattr(run_ctx, "elapsed_seconds", 0.0),
                    },
                )
            )
            raise
        finally:
            if (
                self._trace_recorder is not None
                and trace_run_span_id is not None
                and SpanStatus is not None
            ):
                try:
                    status = SpanStatus.ERROR if bool(getattr(run_ctx, "failed", False)) else SpanStatus.OK
                    await self._trace_recorder.end_span(
                        resolved_run_id,
                        trace_run_span_id,
                        status=status,  # type: ignore[arg-type]
                        output_preview=f"agent={self.agent_type}",
                        error=str(getattr(run_ctx, "failure_class", "") or "") or None,
                    )
                except Exception as exc:
                    logger.debug("HR trace run end skipped: %s", exc)


class ResumeParserHarnessAgent(_HRHarnessAgentBase):
    agent_type = "resume_parser"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        parser = ResumeParserAgent()
        parsed = await parser(
            {
                "text": task_data.get("text") or task_data.get("resume_text") or task_data.get("doc_text") or "",
            }
        )
        return parsed if isinstance(parsed, dict) else {"parsed_resume": parsed}


class EmbeddingHarnessAgent(_HRHarnessAgentBase):
    agent_type = "embedding"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        embedder = EmbeddingAgent()
        result = await embedder({"embed_text": task_data.get("text") or task_data.get("embed_text") or ""})
        return result if isinstance(result, dict) else {"embedding": result}


class DeduplicationHarnessAgent(_HRHarnessAgentBase):
    agent_type = "deduplication"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        dedup = DeduplicationAgent()
        result = await dedup(
            {
                "content": _decode_file_bytes(task_data),
                "candidate_email": task_data.get("candidate_email") or task_data.get("email"),
                "job_id": task_data.get("job_id"),
                "db": None,
            }
        )
        return result if isinstance(result, dict) else {"is_duplicate": False}


class ResumeScorerHarnessAgent(_HRHarnessAgentBase):
    agent_type = "resume_scorer"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        scorer = ScoringAgent()
        result = await scorer(
            {
                "parsed_resume": task_data.get("parsed_resume") or {},
                "parsed_job": _build_parsed_job(task_data),
                "jd_embedding": task_data.get("jd_embedding") or [],
                "skip_ai_scoring": bool(task_data.get("skip_ai_scoring", False)),
            }
        )
        return result if isinstance(result, dict) else {"score_result": result}


class JDParserHarnessAgent(_HRHarnessAgentBase):
    agent_type = "jd_parser"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        parser = JDParserAgent()
        result = await parser(
            {
                "jd_text": task_data.get("doc_text") or task_data.get("jd_text") or task_data.get("job_description") or "",
            }
        )
        return result if isinstance(result, dict) else {"parsed_job": result}


class JDGeneratorHarnessAgent(_HRHarnessAgentBase):
    agent_type = "jd_generator"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        generator = JDGeneratorAgent()
        result = await generator(
            {
                "role": task_data.get("role") or "",
                "experience_min": _ensure_int(task_data.get("experience_min"), 0),
                "experience_max": _ensure_int(task_data.get("experience_max"), 5),
                "location": task_data.get("location") or "Remote",
                "additional_context": task_data.get("additional_context") or task_data.get("context") or "",
            }
        )
        return result if isinstance(result, dict) else {"jd_data": result}


class QuizGeneratorHarnessAgent(_HRHarnessAgentBase):
    agent_type = "quiz_generator"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        quiz = QuizAgent()
        result = await quiz(
            {
                "operation": "generate",
                "jd_text": task_data.get("jd_text") or "",
                "skills": _ensure_list(task_data.get("skills")),
                "easy": _ensure_int(task_data.get("easy"), 8),
                "medium": _ensure_int(task_data.get("medium"), 8),
                "hard": _ensure_int(task_data.get("hard"), 4),
            }
        )
        return result if isinstance(result, dict) else {"questions": result}


class QuizParserHarnessAgent(_HRHarnessAgentBase):
    agent_type = "quiz_parser"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        quiz = QuizAgent()
        result = await quiz(
            {
                "operation": "parse_document",
                "doc_text": task_data.get("doc_text") or "",
            }
        )
        return result if isinstance(result, dict) else {"questions": result}


class CodeEvaluatorHarnessAgent(_HRHarnessAgentBase):
    agent_type = "code_evaluator"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        evaluator = CodeEvaluationAgent()
        result = await evaluator(
            {
                "problem_statement": task_data.get("problem_statement") or task_data.get("problem") or "",
                "user_code": task_data.get("user_code") or task_data.get("code") or "",
                "language": task_data.get("language") or "python",
            }
        )
        return result if isinstance(result, dict) else {"code_eval_result": result}


class CandidateRankerHarnessAgent(_HRHarnessAgentBase):
    agent_type = "candidate_ranker"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        ranker = RankingAgent()
        result = await ranker(
            {
                "jd": task_data.get("jd") or {},
                "candidates": task_data.get("candidates") or [],
                "use_lyzr": bool(task_data.get("use_lyzr", True)),
            }
        )
        return result if isinstance(result, dict) else {"ranking_result": result}


class ResumeEnhancerHarnessAgent(_HRHarnessAgentBase):
    agent_type = "resume_enhancer"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        enhancer = ResumeEnhancerAgent()
        result = await enhancer(
            {
                "resume_text": task_data.get("resume_text") or "",
                "parsed_job": _build_parsed_job(task_data),
                "parsed_resume": task_data.get("parsed_resume") or {},
            }
        )
        return result if isinstance(result, dict) else {"enhancement_result": result}


class ResumeBuilderHarnessAgent(_HRHarnessAgentBase):
    agent_type = "resume_builder"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        builder = ResumeBuilderAgent()
        result = await builder(
            {
                "candidate_data": task_data.get("candidate_data") or {},
                "target_role": task_data.get("target_role") or "",
            }
        )
        return result if isinstance(result, dict) else {"built_resume": result}


class CoverLetterHarnessAgent(_HRHarnessAgentBase):
    agent_type = "cover_letter"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        cover = CoverLetterAgent()
        parsed_resume = task_data.get("parsed_resume") or {}
        parsed_job = _build_parsed_job(task_data)
        result = await cover(
            {
                "parsed_resume": parsed_resume,
                "parsed_job": parsed_job,
                "candidate_name": task_data.get("candidate_name") or parsed_resume.get("name") or "Candidate",
                "company_name": task_data.get("company_name") or "the company",
            }
        )
        return result if isinstance(result, dict) else {"cover_letter": result}


class CareerAnalystHarnessAgent(_HRHarnessAgentBase):
    agent_type = "career_analyst"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        analyst = CareerAnalystAgent()
        result = await analyst(
            {
                "candidate_name": task_data.get("candidate_name") or "Candidate",
                "target_role": task_data.get("target_role") or "Software Engineer",
                "experience_years": _ensure_float(task_data.get("exp_years", task_data.get("experience_years")), 0.0),
                "skills": task_data.get("skills") or [],
                "work_history": task_data.get("work_history") or [],
                "education": task_data.get("education") or [],
                "career_breaks": task_data.get("career_breaks") or [],
            }
        )
        return result if isinstance(result, dict) else {"career_analysis": result}


class HREmailDraftHarnessAgent(_HRHarnessAgentBase):
    agent_type = "hr_email_draft"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        notifier = NotificationAgent()
        result = await notifier(
            {
                "operation": "hr_email_draft",
                "email_type": task_data.get("email_type") or "general",
                "candidate_name": task_data.get("candidate_name") or "Candidate",
                "job_title": task_data.get("job_title") or "Role",
                "resume_score": _ensure_float(task_data.get("resume_score"), 0.0),
                "quiz_score": _ensure_float(task_data.get("quiz_score"), 0.0),
                "to_email": task_data.get("to_email") or "",
            }
        )
        return result if isinstance(result, dict) else {"email_draft": result}


class ResumePipelineHarnessAgent(_HRHarnessAgentBase):
    agent_type = "resume_pipeline"

    async def _execute(self, task_data: dict[str, Any]) -> dict[str, Any]:
        content = _decode_file_bytes(task_data)
        if not content:
            raise ValueError("resume_pipeline requires content_b64 or file_bytes_b64")

        filename = str(task_data.get("filename") or "resume.pdf")
        parsed_job = _build_parsed_job(task_data)

        state: dict[str, Any] = {
            "filename": filename,
            "content": content,
            "parsed_job": parsed_job,
            "job_id": task_data.get("job_id"),
            "candidate_email": task_data.get("candidate_email"),
            "skip_ai_scoring": bool(task_data.get("skip_ai_scoring", False)),
        }

        extractor = FileExtractionAgent()
        parser = ResumeParserAgent()
        embedder = EmbeddingAgent()
        dedup = DeduplicationAgent()
        scorer = ScoringAgent()

        state.update(await extractor(state))
        state.update(await parser(state))
        state.update(await embedder(state))
        state.update(await dedup(state))
        state.update(await scorer(state))
        return state


_HR_AGENT_FACTORY: dict[str, type[_HRHarnessAgentBase]] = {
    ResumeParserHarnessAgent.agent_type: ResumeParserHarnessAgent,
    EmbeddingHarnessAgent.agent_type: EmbeddingHarnessAgent,
    DeduplicationHarnessAgent.agent_type: DeduplicationHarnessAgent,
    ResumeScorerHarnessAgent.agent_type: ResumeScorerHarnessAgent,
    JDParserHarnessAgent.agent_type: JDParserHarnessAgent,
    JDGeneratorHarnessAgent.agent_type: JDGeneratorHarnessAgent,
    QuizGeneratorHarnessAgent.agent_type: QuizGeneratorHarnessAgent,
    QuizParserHarnessAgent.agent_type: QuizParserHarnessAgent,
    CodeEvaluatorHarnessAgent.agent_type: CodeEvaluatorHarnessAgent,
    CandidateRankerHarnessAgent.agent_type: CandidateRankerHarnessAgent,
    ResumeEnhancerHarnessAgent.agent_type: ResumeEnhancerHarnessAgent,
    ResumeBuilderHarnessAgent.agent_type: ResumeBuilderHarnessAgent,
    CoverLetterHarnessAgent.agent_type: CoverLetterHarnessAgent,
    CareerAnalystHarnessAgent.agent_type: CareerAnalystHarnessAgent,
    HREmailDraftHarnessAgent.agent_type: HREmailDraftHarnessAgent,
    ResumePipelineHarnessAgent.agent_type: ResumePipelineHarnessAgent,
}

HR_AGENT_TYPES: set[str] = set(_HR_AGENT_FACTORY.keys())


def build_hr_agent(agent_type: str) -> _HRHarnessAgentBase:
    cls = _HR_AGENT_FACTORY.get(agent_type)
    if cls is None:
        raise ValueError(f"Unknown HR harness agent_type: {agent_type!r}")
    return cls()
