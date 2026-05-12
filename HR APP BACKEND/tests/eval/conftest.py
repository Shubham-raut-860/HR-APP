"""
Shared pytest fixtures for DeepEval, RAGAS, and MLflow test suites.

Sets up:
  - azure_judge               : DeepEvalBaseLLM backed by Azure OpenAI
  - ragas_evaluator_fixture   : RagasService singleton instance
  - mlflow_client             : MLflow client (optional, skips if not configured)
  - golden_dataset            : test cases from golden_dataset.json
  - event_loop_policy         : asyncio default policy for deepeval async tests
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# â”€â”€ Make sure the project root is on sys.path â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")


# â”€â”€ Golden dataset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@pytest.fixture(scope="session")
def golden_dataset() -> dict:
    dataset_path = _project_root / "app" / "evals" / "datasets" / "golden_dataset.json"
    with open(dataset_path, encoding="utf-8") as f:
        return json.load(f)


# â”€â”€ DeepEval: Azure LLM judge â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@pytest.fixture(scope="session")
def azure_judge():
    """Configured AzureJudge for DeepEval metrics. Skips if no API key."""
    if os.getenv("RUN_LLM_EVAL_TESTS", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("RUN_LLM_EVAL_TESTS not enabled; skipping network-backed eval tests")
    if not os.getenv("AZURE_OPENAI_API_KEY", ""):
        pytest.skip("AZURE_OPENAI_API_KEY not set â€” skipping LLM-judge tests")
    from app.evals.deepeval_service import _build_azure_evaluator_model
    judge = _build_azure_evaluator_model()
    if judge is None:
        pytest.skip("deepeval not installed")
    return judge


# â”€â”€ RAGAS evaluator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@pytest.fixture(scope="session")
def ragas_evaluator_fixture():
    """RagasService singleton. Skips if RAGAS not installed or no Azure key."""
    if os.getenv("RUN_LLM_EVAL_TESTS", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("RUN_LLM_EVAL_TESTS not enabled; skipping network-backed eval tests")
    if not os.getenv("AZURE_OPENAI_API_KEY", ""):
        pytest.skip("AZURE_OPENAI_API_KEY not set â€” skipping RAGAS tests")
    try:
        from app.evals.ragas_service import ragas_evaluator
        return ragas_evaluator
    except ImportError as e:
        pytest.skip(f"RAGAS dependencies not installed: {e}")


# â”€â”€ MLflow client (optional) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@pytest.fixture(scope="session")
def mlflow_client():
    """Returns an mlflow.tracking.MlflowClient, or None if not installed."""
    try:
        import mlflow
        from app.config import settings
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        return mlflow.tracking.MlflowClient()
    except Exception:
        return None


# â”€â”€ Async event loop policy â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@pytest.fixture(scope="session")
def event_loop_policy():
    """Use asyncio default policy (required for deepeval async tests)."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()
