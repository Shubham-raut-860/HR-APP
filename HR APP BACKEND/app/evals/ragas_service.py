"""
RAGAS evaluation service for HireAI.

RAGAS (Retrieval-Augmented Generation Assessment) provides RAG-specific
metrics that complement DeepEval's general LLM-judge approach.

In the HireAI context, the resume pipeline IS a RAG pipeline:
  - context  = resume_text (retrieved/extracted from the file)
  - question = jd_text     (the query driving what to look for)
  - answer   = parsed_output / scores (the generated answer)

Metrics provided:
  ┌────────────────────┬────────────────────────────────────────────────┐
  │ Faithfulness       │ Is the answer supported by the resume text?    │
  │ Answer Relevancy   │ Does the output address what the JD asked for? │
  │ Context Precision  │ Is the resume content relevant to the JD?      │
  │ Context Recall     │ Does the resume cover all required skills?      │
  └────────────────────┴────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RagasResult:
    metrics: dict[str, float]        # metric_name → score
    passed: bool
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "library":    "ragas",
            "passed":     self.passed,
            "metrics":    {k: round(v, 4) for k, v in self.metrics.items()},
            "latency_ms": round(self.latency_ms, 1),
            "error":      self.error,
        }


def _build_ragas_llm():
    """
    Build a LangChain-compatible Azure OpenAI wrapper for RAGAS.
    RAGAS uses LangChain's LLM interface internally.
    """
    try:
        from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

        _endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/").removesuffix("/openai/v1")

        class SafeAzureChatOpenAI(AzureChatOpenAI):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                kwargs["temperature"] = 1
                return super()._generate(messages, stop, run_manager, **kwargs)

            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                kwargs["temperature"] = 1
                return await super()._agenerate(messages, stop, run_manager, **kwargs)

        llm = SafeAzureChatOpenAI(
            azure_deployment=settings.AZURE_CHAT_DEPLOYMENT,
            azure_endpoint=_endpoint,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            temperature=1,
        )
        embeddings = AzureOpenAIEmbeddings(
            azure_deployment=settings.AZURE_EMBEDDING_DEPLOYMENT,
            azure_endpoint=_endpoint,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
        return llm, embeddings
    except ImportError as exc:
        logger.warning("langchain-openai not installed — RAGAS will be unavailable. (%s)", exc)
        return None, None


class RagasService:
    """
    Thin async wrapper around RAGAS evaluate().

    Usage:
        from app.evals.ragas_service import ragas_evaluator

        result = await ragas_evaluator.evaluate_resume_parsing(
            resume_text="...", parsed_output={...}, jd_text="..."
        )
        result = await ragas_evaluator.evaluate_resume_scoring(
            resume_text="...", jd_text="...", scores={...}
        )
    """

    def __init__(self):
        self._available = False
        try:
            import ragas  # noqa: F401
            import datasets  # noqa: F401
            import langchain_openai  # noqa: F401
            self._available = bool(settings.AZURE_OPENAI_API_KEY)
            if self._available:
                logger.info("✅ RAGAS service initialised (Azure OpenAI backend).")
            else:
                logger.warning("⚠️  RAGAS available but AZURE_OPENAI_API_KEY not set.")
        except ImportError as exc:
            logger.warning(
                "⚠️  RAGAS not installed — run `pip install ragas langchain-openai`. (%s)", exc)

    def _raise_unavailable(self) -> None:
        logger.error("RAGAS unavailable (missing dependencies/config).")
        raise RuntimeError("Evaluator unavailable")

    async def evaluate_resume_parsing(
        self,
        resume_text: str,
        parsed_output: dict,
        jd_text: str,
        ground_truth: dict | None = None,
    ) -> RagasResult:
        """
        Evaluate resume parsing with RAGAS RAG metrics.

        Maps:
          context  = resume_text
          question = jd_text (drives what fields are important)
          answer   = json.dumps(parsed_output)
          ground_truth = json.dumps(ground_truth) if provided
        """
        if not self._available:
            self._raise_unavailable()

        from ragas.metrics import faithfulness, answer_relevancy, context_precision

        answer = json.dumps(parsed_output, ensure_ascii=False)
        gt = json.dumps(ground_truth, ensure_ascii=False) if ground_truth else answer

        data = {
            "question":     [jd_text],
            "contexts":     [[resume_text]],
            "answer":       [answer],
            "ground_truth": [gt],
        }
        return await self._run(data, [faithfulness, answer_relevancy, context_precision])

    async def evaluate_resume_scoring(
        self,
        resume_text: str,
        jd_text: str,
        scores: dict,
    ) -> RagasResult:
        """
        Evaluate resume scoring with RAGAS.

        Maps:
          context  = resume_text
          question = jd_text
          answer   = json.dumps(scores)
        """
        if not self._available:
            self._raise_unavailable()

        from ragas.metrics import faithfulness, answer_relevancy, context_recall

        answer = json.dumps(scores, ensure_ascii=False)

        data = {
            "question":     [jd_text],
            "contexts":     [[resume_text]],
            "answer":       [answer],
            "ground_truth": [jd_text],  # ground truth = what the JD requires
        }
        return await self._run(data, [faithfulness, answer_relevancy, context_recall])

    async def _run(self, data: dict, metrics: list) -> RagasResult:
        import asyncio
        from datasets import Dataset

        llm, embeddings = _build_ragas_llm()
        if llm is None:
            self._raise_unavailable()

        t0 = time.perf_counter()
        try:
            dataset = Dataset.from_dict(data)

            # BUG #4 FIX: asyncio.get_event_loop() is deprecated in Python ≥3.10
            # and raises DeprecationWarning / errors in 3.12+.
            # Inside an async function the running loop is always available via
            # asyncio.get_running_loop(); there is no need to create a new one.
            loop = asyncio.get_running_loop()
            from ragas import evaluate

            result = await loop.run_in_executor(
                None,
                lambda: evaluate(
                    dataset,
                    metrics=metrics,
                    llm=llm,
                    embeddings=embeddings,
                ),
            )

            latency_ms = (time.perf_counter() - t0) * 1000
            scores_dict = {}
            for m in metrics:
                val = result[m.name]
                scores_dict[m.name] = float(val[0]) if isinstance(val, list) else float(val)
            passed = all(v >= 0.5 for v in scores_dict.values())

            return RagasResult(
                metrics=scores_dict,
                passed=passed,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            logger.error("RAGAS evaluation failed: %s", exc)
            return RagasResult(
                metrics={},
                passed=False,
                latency_ms=(time.perf_counter() - t0) * 1000,
                error=str(exc),
            )


# ─── Singleton ────────────────────────────────────────────────────────────────

ragas_evaluator = RagasService()
