"""
DeepEval evaluation service for HireAI.

Merges DeepEval (primary eval engine) with Langfuse (observability) into one
unified evaluation layer. Every LLM operation in the platform — resume parsing,
resume scoring, and JD generation — has a dedicated set of metrics here.

Architecture:
  ┌────────────┐    results    ┌─────────────────┐   traces  ┌──────────┐
  │  HireAI    │ ───────────► │  DeepEvalService │ ────────► │ Langfuse │
  │  Routers   │              │  (this module)   │           │  Cloud   │
  └────────────┘              └─────────────────┘           └──────────┘
                                       │
                              metrics + scores
                                       │
                              ┌────────▼────────┐
                              │  Confident AI / │
                              │  local reports  │
                              └─────────────────┘

Metric registry (per operation):
  ┌──────────────────┬──────────────────────────────────────────────────┐
  │ Resume Parsing   │ extraction_completeness (GEval)                  │
  │                  │ field_accuracy          (GEval)                  │
  │                  │ hallucination           (HallucinationMetric)    │
  ├──────────────────┼──────────────────────────────────────────────────┤
  │ Resume Scoring   │ scoring_fairness        (GEval)                  │
  │                  │ scoring_consistency     (GEval)                  │
  │                  │ score_range_validity    (DAGMetric)              │
  ├──────────────────┼──────────────────────────────────────────────────┤
  │ JD Generation    │ answer_relevancy        (AnswerRelevancyMetric)  │
  │                  │ jd_completeness         (GEval)                  │
  │                  │ jd_clarity              (GEval)                  │
  └──────────────────┴──────────────────────────────────────────────────┘

Usage (from a FastAPI route):
    from app.evals.deepeval_service import evaluator

    result = await evaluator.evaluate_resume_parsing(
        resume_text="... raw resume text ...",
        parsed_output={"name": "Jane Doe", "skills": ["Python"]},
    )
    result = await evaluator.evaluate_resume_scoring(
        resume_text="...", jd_text="...", scores={"skill_score": 75, ...}
    )
    result = await evaluator.evaluate_jd_generation(
        user_input="Senior Python Engineer ...", generated_jd="..."
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


# ─── Custom Azure OpenAI judge model ─────────────────────────────────────────

def _build_azure_evaluator_model():
    """
    Build a DeepEvalBaseLLM subclass backed by the project's Azure OpenAI
    deployment.  Returns None if deepeval or openai is not installed.
    """
    try:
        from deepeval.models.base_model import DeepEvalBaseLLM
        from openai import AzureOpenAI, AsyncAzureOpenAI as AsyncAzure

        _endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/").removesuffix("/openai/v1")
        _key = settings.AZURE_OPENAI_API_KEY
        _version = settings.AZURE_OPENAI_API_VERSION
        _deploy = settings.AZURE_CHAT_DEPLOYMENT

        class _AzureJudge(DeepEvalBaseLLM):
            """Thin DeepEval wrapper around the project's Azure OpenAI client.

            BUG #5 FIX: load_model() was being called on every generate/a_generate
            invocation, creating a brand-new AzureOpenAI client for every single
            LLM judge call. That is ~10x slower than necessary. Both the sync and
            async clients are now created once and cached as instance attributes.
            """

            def __init__(self, model=None, *args, **kwargs):
                # BUG #5 FIX: DeepEvalBaseLLM.__init__() calls self.load_model()
                # internally, so we MUST set the client attributes BEFORE calling
                # super().__init__(), otherwise load_model() hits AttributeError.
                self._sync_client = AzureOpenAI(
                    azure_endpoint=_endpoint,
                    api_key=_key,
                    api_version=_version,
                )
                self._async_client = AsyncAzure(
                    azure_endpoint=_endpoint,
                    api_key=_key,
                    api_version=_version,
                )
                super().__init__(model=model, *args, **kwargs)

            def load_model(self):
                return self._sync_client

            def generate(self, prompt: str, schema=None) -> str | Any:
                response = self._sync_client.chat.completions.create(
                    model=_deploy,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.choices[0].message.content.strip()
                if schema is not None:
                    try:
                        return schema.model_validate_json(text)
                    except Exception:
                        return text
                return text

            async def a_generate(self, prompt: str, schema=None) -> str | Any:
                response = await self._async_client.chat.completions.create(
                    model=_deploy,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.choices[0].message.content.strip()
                if schema is not None:
                    try:
                        return schema.model_validate_json(text)
                    except Exception:
                        return text
                return text

            def get_model_name(self) -> str:
                return f"azure-openai/{_deploy}"

        return _AzureJudge()

    except Exception as exc:
        logger.warning(
            "deepeval or openai not installed/configured — evaluator will be a no-op. (%s)", exc
        )
        return None


# ─── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class MetricResult:
    name: str
    score: float
    passed: bool
    reason: str
    threshold: float


@dataclass
class EvalResult:
    operation: str           # resume_parsing | resume_scoring | jd_generation
    passed: bool
    overall_score: float
    metrics: list[MetricResult] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "operation":     self.operation,
            "passed":        self.passed,
            "overall_score": round(self.overall_score, 4),
            "latency_ms":    round(self.latency_ms, 1),
            "error":         self.error,
            "metrics": [
                {
                    "name":      m.name,
                    "score":     round(m.score, 4),
                    "passed":    m.passed,
                    "threshold": m.threshold,
                    "reason":    m.reason,
                }
                for m in self.metrics
            ],
        }


# ─── Metric factories ─────────────────────────────────────────────────────────

def _make_resume_parsing_metrics(judge):
    """GEval + Hallucination metrics for the resume parser."""
    from deepeval.metrics import GEval, HallucinationMetric
    from deepeval.test_case import LLMTestCaseParams

    extraction_completeness = GEval(
        name="Extraction Completeness",
        criteria=(
            "Evaluate whether the parsed output contains all key resume fields: "
            "full name, email, phone, location, skills list, work experience "
            "(company, role, duration), education, and any certifications. "
            "Score higher when more fields are populated and none are incorrectly absent."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=judge,
        threshold=0.6,
    )

    field_accuracy = GEval(
        name="Field Accuracy",
        criteria=(
            "Verify that each extracted field value matches what is explicitly stated "
            "in the original resume text (the INPUT). Penalise hallucinated values, "
            "swapped fields (e.g. company name used as job title), or numeric errors "
            "such as wrong years of experience."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=judge,
        threshold=0.7,
    )

    hallucination = HallucinationMetric(
        threshold=0.2,   # lower is better — allow at most 20 % hallucination rate
        model=judge,
    )

    return [extraction_completeness, field_accuracy, hallucination]


def _make_resume_scoring_metrics(judge):
    """GEval + DAGMetric metrics for the AI resume scorer."""
    from deepeval.metrics import GEval, DAGMetric
    from deepeval.metrics.dag import (
        NonLLMTask,
    )
    from deepeval.test_case import LLMTestCaseParams

    scoring_fairness = GEval(
        name="Scoring Fairness",
        criteria=(
            "Given the job description (EXPECTED_OUTPUT) and the candidate's resume "
            "(INPUT), evaluate whether the skill_score, experience_score, and "
            "project_score in ACTUAL_OUTPUT are proportional and justified. "
            "A candidate clearly missing required skills should score below 50. "
            "A strong match should score above 70. "
            "Penalise scores that contradict obvious evidence in the resume."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        model=judge,
        threshold=0.65,
    )

    scoring_consistency = GEval(
        name="Scoring Consistency",
        criteria=(
            "Evaluate whether the three component scores (skill_score, "
            "experience_score, project_score) are internally consistent with "
            "each other given the resume content and JD. For example, if the "
            "candidate has 10 years of Python experience, skill_score and "
            "experience_score should both be high. Flag cases where one dimension "
            "is implausibly much higher or lower than the others without clear reason."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=judge,
        threshold=0.6,
    )

    # DAGMetric — deterministic range validation (no LLM needed for this check)
    score_range_node = NonLLMTask(
        name="Score Range Validity",
        evaluation_function=lambda tc: _validate_score_ranges(tc.actual_output),
    )
    score_range_validity = DAGMetric(
        name="Score Range Validity",
        dag=score_range_node,
        model=judge,
        threshold=0.5,
    )

    return [scoring_fairness, scoring_consistency, score_range_validity]


def _validate_score_ranges(actual_output: str) -> float:
    """
    Non-LLM validator: ensure all score values are in [0, 100].
    Returns 1.0 if valid, 0.0 if any value is out of range.
    """
    try:
        data = json.loads(actual_output) if isinstance(actual_output, str) else actual_output
        score_keys = ["skill_score", "experience_score", "project_score"]
        for k in score_keys:
            if k in data:
                v = float(data[k])
                if not (0.0 <= v <= 100.0):
                    return 0.0
        return 1.0
    except Exception:
        return 0.0


def _make_jd_generation_metrics(judge):
    """AnswerRelevancy + GEval metrics for the JD generator."""
    from deepeval.metrics import AnswerRelevancyMetric, GEval
    from deepeval.test_case import LLMTestCaseParams

    answer_relevancy = AnswerRelevancyMetric(
        threshold=0.7,
        model=judge,
        include_reason=True,
    )

    jd_completeness = GEval(
        name="JD Completeness",
        criteria=(
            "Evaluate whether the generated job description (ACTUAL_OUTPUT) includes "
            "all essential sections: job title, role overview/summary, key "
            "responsibilities (≥ 3 bullet points), required skills/qualifications, "
            "and preferred qualifications or nice-to-haves. "
            "Score 1.0 if all sections are present and non-trivial."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=judge,
        threshold=0.7,
    )

    jd_clarity = GEval(
        name="JD Clarity",
        criteria=(
            "Assess the writing quality of the generated job description. "
            "It should use clear, professional language; avoid vague filler phrases "
            "('rockstar', 'ninja'); list concrete, measurable responsibilities; "
            "and be free of grammatical errors. Score based on readability and "
            "specificity rather than length."
        ),
        evaluation_params=[
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=judge,
        threshold=0.65,
    )

    return [answer_relevancy, jd_completeness, jd_clarity]


# ─── Main service class ───────────────────────────────────────────────────────

class DeepEvalService:
    """
    Unified evaluation service.  Instantiate once at startup (singleton pattern).

    All evaluate_* methods are async-safe and can be called from FastAPI routes
    or background tasks.  Results are returned as EvalResult dataclasses and
    can optionally be forwarded to Langfuse as trace metadata.
    """

    def __init__(self):
        # Keep startup safe: defer deepeval/openai imports until first eval call.
        self._judge = None
        self._available = False
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._judge = _build_azure_evaluator_model()
        self._available = self._judge is not None
        self._initialized = True
        if self._available:
            logger.info("✅ DeepEval service initialised with Azure OpenAI judge (%s).",
                        self._judge.get_model_name())
        else:
            logger.warning("⚠️  DeepEval service running in no-op mode (missing dependencies/config).")

    # ── internal helpers ──────────────────────────────────────────────────────

    def _raise_unavailable(self, operation: str) -> None:
        logger.error(
            "DeepEval unavailable for operation '%s' (missing dependencies/config).",
            operation,
        )
        raise RuntimeError("Evaluator unavailable")

    async def _run_metrics(
        self,
        operation: str,
        test_case,               # deepeval.test_case.LLMTestCase
        metrics: list,
    ) -> EvalResult:
        """Execute a list of deepeval metrics against a test case asynchronously."""

        t0 = time.perf_counter()
        results: list[MetricResult] = []

        async def _measure(metric, tc):
            try:
                await metric.a_measure(tc)
                return MetricResult(
                    name=metric.name,
                    score=float(metric.score),
                    passed=metric.is_successful(),
                    reason=getattr(metric, "reason", "") or "",
                    threshold=float(metric.threshold),
                )
            except Exception as exc:
                logger.error("Metric '%s' failed: %s", metric.name, exc)
                return MetricResult(
                    name=metric.name,
                    score=0.0,
                    passed=False,
                    reason=str(exc),
                    threshold=float(getattr(metric, "threshold", 0.5)),
                )

        tasks = [_measure(m, test_case) for m in metrics]
        results = list(await asyncio.gather(*tasks))

        latency_ms = (time.perf_counter() - t0) * 1000
        scores = [r.score for r in results]
        overall = sum(scores) / len(scores) if scores else 0.0
        passed = all(r.passed for r in results)

        return EvalResult(
            operation=operation,
            passed=passed,
            overall_score=overall,
            metrics=results,
            latency_ms=latency_ms,
        )

    # ── public API ────────────────────────────────────────────────────────────

    async def evaluate_resume_parsing(
        self,
        resume_text: str,
        parsed_output: dict,
        contexts: list[str] | None = None,
    ) -> EvalResult:
        """
        Evaluate the resume parser.

        Args:
            resume_text:   Raw text extracted from the uploaded resume file.
            parsed_output: Dict returned by gemini_service.parse_resume().
            contexts:      Optional list of context strings for hallucination check.
        """
        self._ensure_initialized()
        if not self._available:
            self._raise_unavailable("resume_parsing")

        from deepeval.test_case import LLMTestCase

        tc = LLMTestCase(
            input=resume_text,
            actual_output=json.dumps(parsed_output, ensure_ascii=False),
            context=contexts or [resume_text],
        )
        metrics = _make_resume_parsing_metrics(self._judge)
        return await self._run_metrics("resume_parsing", tc, metrics)

    async def evaluate_resume_scoring(
        self,
        resume_text: str,
        jd_text: str,
        scores: dict,
    ) -> EvalResult:
        """
        Evaluate the AI resume scorer.

        Args:
            resume_text: Raw resume text (used as INPUT).
            jd_text:     Full job description text (used as EXPECTED_OUTPUT).
            scores:      Dict with skill_score, experience_score, project_score.
        """
        self._ensure_initialized()
        if not self._available:
            self._raise_unavailable("resume_scoring")

        from deepeval.test_case import LLMTestCase

        tc = LLMTestCase(
            input=resume_text,
            actual_output=json.dumps(scores, ensure_ascii=False),
            expected_output=jd_text,
        )
        metrics = _make_resume_scoring_metrics(self._judge)
        return await self._run_metrics("resume_scoring", tc, metrics)

    async def evaluate_jd_generation(
        self,
        user_input: str,
        generated_jd: str,
    ) -> EvalResult:
        """
        Evaluate the JD generator.

        Args:
            user_input:    The prompt / brief the user provided.
            generated_jd:  The full JD text returned by gemini_service.generate_jd().
        """
        self._ensure_initialized()
        if not self._available:
            self._raise_unavailable("jd_generation")

        from deepeval.test_case import LLMTestCase

        tc = LLMTestCase(
            input=user_input,
            actual_output=generated_jd,
        )
        metrics = _make_jd_generation_metrics(self._judge)
        return await self._run_metrics("jd_generation", tc, metrics)

    async def evaluate_all(
        self,
        *,
        resume_text: str,
        parsed_output: dict,
        jd_text: str,
        scores: dict,
        generated_jd: str | None = None,
        user_jd_input: str | None = None,
    ) -> dict[str, EvalResult]:
        """
        Run all evaluations for a full resume pipeline in parallel and return
        a dict keyed by operation name.
        """
        tasks: dict[str, Any] = {
            "resume_parsing": self.evaluate_resume_parsing(
                resume_text=resume_text,
                parsed_output=parsed_output,
            ),
            "resume_scoring": self.evaluate_resume_scoring(
                resume_text=resume_text,
                jd_text=jd_text,
                scores=scores,
            ),
        }
        if generated_jd and user_jd_input:
            tasks["jd_generation"] = self.evaluate_jd_generation(
                user_input=user_jd_input,
                generated_jd=generated_jd,
            )

        results_list = await asyncio.gather(*tasks.values())
        return dict(zip(tasks.keys(), results_list))


# ─── Singleton ────────────────────────────────────────────────────────────────

evaluator = DeepEvalService()
