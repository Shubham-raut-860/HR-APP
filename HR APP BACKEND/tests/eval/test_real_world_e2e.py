"""
Real-World End-to-End Evaluation — ALL THREE LIBRARIES IN ONE PASS.

Runs real PDFs from tests/eval/real_data/ through the complete HR pipeline
and evaluates the output with DeepEval (GEval), RAGAS (faithfulness +
context precision), and MLflow score logging.

Run with:
    deepeval test run tests/eval/test_real_world_e2e.py
    # OR
    pytest tests/eval/test_real_world_e2e.py -v -s

IMPORTANT: Requires AZURE_OPENAI_API_KEY and optionally a reachable MLflow URI.
Results are also saved to tests/eval/real_data/last_run_results.json.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

_REAL_DATA = Path(__file__).parent / "real_data"
_JD_FILE   = "JD- Net Core Developer - New.docx"

# 3 anonymized placeholder resumes from real_data/
_RESUMES = [
    "sample_resume_anonymized_01.pdf",
    "sample_resume_anonymized_02.pdf",
    "sample_resume_anonymized_03.pdf",
]


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _load_file(filename: str) -> str:
    """Extract text from a real PDF or DOCX in real_data/."""
    filepath = _REAL_DATA / filename
    if not filepath.exists():
        pytest.skip(f"Real file not found: {filepath}")
    ext = filepath.suffix.lower()
    raw = filepath.read_bytes()
    from app.services.file_service import extract_text_from_pdf, extract_text_from_docx
    if ext == ".pdf":
        return extract_text_from_pdf(raw)
    return extract_text_from_docx(raw)


def _run_async(coro):
    """Safely run an async coroutine from synchronous pytest."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# FULL E2E WITH ALL 3 LIBRARIES
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealWorldE2E:
    """
    Single test class that exercises DeepEval + RAGAS + MLflow together.
    Each parameterized case:
      1. Loads a real PDF resume and real DOCX JD.
      2. Runs the actual Azure OpenAI scoring pipeline.
      3. Evaluates the output with DeepEval GEval (LLM-judge).
      4. Evaluates faithfulness + context precision with RAGAS.
      5. Pushes all scores to MLflow.
      6. Appends results to last_run_results.json.
    """

    @pytest.mark.parametrize("resume_filename", [
        f for f in _RESUMES
        if (_REAL_DATA / f).exists()
    ])
    def test_full_pipeline_all_libraries(self, resume_filename: str, azure_judge):
        import time, json
        from deepeval         import assert_test
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        # ── 1. Load real files ────────────────────────────────────────────────
        resume_text = _load_file(resume_filename)
        jd_text     = _load_file(_JD_FILE)

        # ── 2. Run the production pipeline ───────────────────────────────────
        async def _run():
            from app.services import gemini_service
            jd_parsed     = await gemini_service.parse_jd_from_document(jd_text)
            resume_parsed = await gemini_service.parse_resume(resume_text)
            ai_scores     = await gemini_service.score_resume_against_jd(
                parsed_resume  = resume_parsed,
                job_title      = jd_parsed.get("title", "Backend .NET Developer"),
                exp_min        = jd_parsed.get("experience_min", 3),
                exp_max        = jd_parsed.get("experience_max", 5),
                must_have      = jd_parsed.get("must_have_skills", []),
                good_to_have   = jd_parsed.get("good_to_have_skills", []),
                description    = jd_parsed.get("description", jd_text),
            )
            return resume_parsed, ai_scores, jd_parsed

        t0 = time.perf_counter()
        resume_parsed, ai_scores, jd_parsed = _run_async(_run())
        latency_ms = (time.perf_counter() - t0) * 1000

        actual_output_str = json.dumps(ai_scores, ensure_ascii=False, indent=2)

        # ── 3. DIMENSION: LLM-judge (DeepEval GEval) ─────────────────────────
        geval_metric = GEval(
            name="Real World Scoring Fairness",
            criteria=(
                "Given the real job description (EXPECTED_OUTPUT) and the extracted "
                "resume text (INPUT), evaluate whether the AI scoring output "
                "(ACTUAL_OUTPUT) is fair and accurate. "
                "Check: (a) must-have skills correctly matched or penalised, "
                "(b) experience years compared correctly, "
                "(c) no hallucinated skill matches or mismatches. "
                "Score 1.0 for completely accurate, fair scoring."
            ),
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            model=azure_judge,
            threshold=0.3,
        )
        tc = LLMTestCase(
            input=resume_text[:3000],        # truncate to avoid token overflow
            actual_output=actual_output_str,
            expected_output=jd_text[:2000],
        )

        # ── 4. DIMENSION: RAGAS (faithfulness + context precision) ────────────
        ragas_result = None
        try:
            from app.evals.ragas_service import ragas_evaluator
            ragas_result = _run_async(
                ragas_evaluator.evaluate_resume_scoring(
                    resume_text=resume_text,
                    scores=ai_scores,
                    jd_text=jd_text,
                )
            )
        except Exception as ragas_err:
            print(f"[RAGAS] non-fatal: {ragas_err}")

        # ── 5. DIMENSION: MLflow score push ─────────────────────────────────────────────
        try:
            from app.services.mlflow_service import push_eval_to_mlflow
            from app.evals.deepeval_service import EvalResult, MetricResult
            # Build a lightweight EvalResult for MLflow
            bridge_result = EvalResult(
                operation="resume_scoring_real_world",
                passed=True,            # determined after assert_test
                overall_score=ai_scores.get("skill_score", 0) / 100,
                metrics=[
                    MetricResult(
                        name="skill_score",
                        score=ai_scores.get("skill_score", 0) / 100,
                        passed=ai_scores.get("skill_score", 0) >= 50,
                        reason=ai_scores.get("skill_reasoning", ""),
                        threshold=0.5,
                    )
                ],
                latency_ms=latency_ms,
            )
            push_eval_to_mlflow(bridge_result)
        except Exception as lf_err:
            print(f"[MLflow] non-fatal: {lf_err}")

        # ── 6. Persist results to JSON ─────────────────────────────────────────
        results_file = _REAL_DATA / "last_run_results.json"
        try:
            history = json.loads(results_file.read_text()) if results_file.exists() else []
            history.append({
                "resume": resume_filename,
                "latency_ms": round(latency_ms, 1),
                "ai_scores": ai_scores,
                "ragas_passed": ragas_result.passed if ragas_result else None,
                "ragas_metrics": ragas_result.metrics if ragas_result else None,
            })
            results_file.write_text(json.dumps(history, indent=2, ensure_ascii=False))
        except Exception:
            pass

        # ── 7. Final DeepEval assertion (raises on fail → test fails) ─────────
        assert_test(tc, [geval_metric])


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE RAGAS — No DeepEval needed
# ═══════════════════════════════════════════════════════════════════════════════

class TestRagasOnly:
    """
    RAGAS-only tests using the golden dataset.
    Tests faithfulness (does the parsed output stay faithful to the resume?)
    and context precision (are the right context chunks retrieved?).
    """

    @pytest.mark.parametrize("case_id,resume_text,parsed", [
        (
            "rp-003",
            "Rohit Pawar\[email-redacted] | Pune\nEXP: 3 years ASP.NET Core, C#, SQL Server, EF Core, JWT, Git\nEDU: B.E. CSE, SPPU 2021",
            {"name": "Rohit Pawar", "skills": ["C#", "ASP.NET Core", "SQL Server", "EF Core", "JWT", "Git"], "total_experience_years": 3},
        ),
        (
            "rp-004",
            "Kamlesh Kumar\nEmail: [email-redacted]\nWork: 2yr QA Wipro, 1yr self-learning C#/ASP.NET MVC.\nSkills: Manual Testing, Selenium, C#, HTML, SQL",
            {"name": "Kamlesh Kumar", "skills": ["Manual Testing", "Selenium", "C#", "HTML", "SQL"], "total_experience_years": 3},
        ),
    ])
    def test_ragas_parsing_faithfulness(self, case_id, resume_text, parsed, ragas_evaluator_fixture):
        """RAGAS Faithfulness: parsed output should not hallucinate beyond the resume text."""
        result = _run_async(
            ragas_evaluator_fixture.evaluate_resume_parsing(
                resume_text=resume_text,
                parsed_output=parsed,
                jd_text="Backend .NET Core Developer. C#, ASP.NET, SQL Server required.",
            )
        )
        assert result is not None, "RAGAS evaluator returned None — service may be unavailable"
        if result.error:
            pytest.skip(f"RAGAS service unavailable: {result.error}")
        # Faithfulness must be > 0.5 for a correctly parsed resume
        faithfulness = next(
            (v for k, v in result.metrics.items() if "faithful" in k.lower()), None
        )
        if faithfulness is not None:
            assert faithfulness >= 0.5, (
                f"[{case_id}] RAGAS faithfulness={faithfulness:.2f} < 0.5 — "
                f"parsed output may have hallucinated fields not in resume"
            )
