"""
Library Experiment Log — Eval Framework Comparison for Jobora

Evaluated: DeepEval, RAGAS, TruLens-Eval, Langfuse Scores
Decision: merge DeepEval (primary) + RAGAS (RAG metrics) as the top 2.
TruLens dropped — see verdict below.

─────────────────────────────────────────────────────────────────────────────
LIBRARY 1: DeepEval (confident-ai/deepeval)
─────────────────────────────────────────────────────────────────────────────

What it covers:
  - GEval: flexible LLM-judge metric with custom criteria (our primary workhorse)
  - HallucinationMetric: detects fabricated content
  - AnswerRelevancyMetric: checks if output answers the input
  - DAGMetric: composable deterministic + LLM hybrid checks
  - FaithfulnessMetric: output grounded in context
  - ContextualRelevancyMetric, ContextualPrecisionMetric, ContextualRecallMetric
  - BiasMetric, ToxicityMetric, SummarizationMetric
  - pytest + `deepeval test run` CLI integration
  - Confident AI dashboard (optional cloud)

Experiment:
    from deepeval.metrics import GEval, HallucinationMetric
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    metric = GEval(
        name="Resume Extraction Completeness",
        criteria="Does the output contain name, email, skills, experience, education?",
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=azure_judge,
        threshold=0.6,
    )
    tc = LLMTestCase(input=resume_text, actual_output=json.dumps(parsed))
    metric.measure(tc)
    # → score: 0.84, passed: True, reason: "All major fields present..."

Verdict: ✅ SELECTED — PRIMARY
  Pros:
    + Most flexible (GEval handles any custom criteria)
    + Best pytest integration (deepeval test run)
    + Azure OpenAI judge works out of the box
    + DAGMetric allows non-LLM validators (our score range check)
    + Active development, good docs
  Cons:
    - No native RAG-specific metrics (faithfulness needs manual criteria)
    - Confident AI dashboard requires internet access

─────────────────────────────────────────────────────────────────────────────
LIBRARY 2: RAGAS (explodinggradients/ragas)
─────────────────────────────────────────────────────────────────────────────

What it covers:
  - Faithfulness: is the answer supported by the retrieved context?
  - AnswerRelevancy: does the answer address the question?
  - ContextPrecision: are retrieved chunks relevant?
  - ContextRecall: are all needed facts in the retrieved context?
  - AnswerCorrectness: factual accuracy vs ground truth
  - AspectCritique: custom aspect-based critique (similar to GEval)

When it applies to Jobora:
  Our resume pipeline is a retrieval-augmented workflow:
    1. Resume text (context) is retrieved/extracted
    2. LLM generates a parsed output or score (answer)
    3. JD (question/query) drives what to look for

  This maps cleanly to RAGAS:
    - resume_text → context
    - parsed_output / scores → answer
    - jd_text → question

Experiment:
    from ragas.metrics import faithfulness, answer_relevancy, context_precision
    from ragas import evaluate
    from datasets import Dataset

    data = {
        "question":  [jd_text],
        "contexts":  [[resume_text]],
        "answer":    [json.dumps(parsed_output)],
        "ground_truth": [json.dumps(expected_parsed)],
    }
    dataset = Dataset.from_dict(data)
    result = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_precision])
    # → {'faithfulness': 0.91, 'answer_relevancy': 0.76, 'context_precision': 0.83}

Verdict: ✅ SELECTED — SECONDARY (RAG-specific metrics)
  Pros:
    + Native RAG evaluation — faithfulness, precision, recall are precise
    + Works with Azure OpenAI via LangChain wrapper
    + Hugging Face dataset format — easy to batch evaluate
    + Answers the question "is the parsed output faithful to the resume?"
  Cons:
    - Requires dataset format (not as flexible for one-off calls)
    - Slower than DeepEval for single evaluations
    - Less pytest-native

─────────────────────────────────────────────────────────────────────────────
LIBRARY 3: TruLens-Eval (truera/trulens)
─────────────────────────────────────────────────────────────────────────────

What it covers:
  - Groundedness: is the answer grounded in the context?
  - Answer Relevance: does it answer the question?
  - Context Relevance: is the retrieved context relevant?
  - Feedback functions: composable eval building blocks
  - TruLens dashboard: local Streamlit UI for traces + scores

Experiment:
    from trulens_eval import Feedback, TruChain
    from trulens_eval.feedback.provider.openai import AzureOpenAI as TruAzure

    provider = TruAzure(deployment_name="gpt-4o", ...)
    f_groundedness = Feedback(provider.groundedness_measure_with_cot_reasons)
        .on_input_output()

    # Problem: TruLens wraps LangChain chains — not bare async functions.
    # Jobora uses raw Azure OpenAI calls, not LangChain.
    # Wrapping them in TruChain required significant refactor.

Verdict: ❌ DROPPED
  Pros:
    + Good groundedness metric with chain-of-thought explanations
    + Nice local dashboard
  Cons:
    - Requires wrapping code in TruChain/TruLlama — invasive refactor
    - Not compatible with bare AsyncAzureOpenAI calls
    - Dashboard is Streamlit (separate process) — not API-native
    - RAGAS covers the same metrics with less friction
    - Slower iteration loop

─────────────────────────────────────────────────────────────────────────────
LIBRARY 4: Langfuse Scores (already integrated)
─────────────────────────────────────────────────────────────────────────────

Role: observability + score storage, not metric computation.
  - Acts as the result sink — DeepEval and RAGAS scores are pushed here
  - Provides the dashboard / UI for HR team to see eval trends over time
  - langfuse_bridge.py handles the score push after each eval run

─────────────────────────────────────────────────────────────────────────────
FINAL DECISION: DeepEval (primary) + RAGAS (secondary) + Langfuse (sink)
─────────────────────────────────────────────────────────────────────────────

Coverage matrix:
  ┌─────────────────────────────┬───────────┬───────────┐
  │ Metric need                 │ DeepEval  │   RAGAS   │
  ├─────────────────────────────┼───────────┼───────────┤
  │ Custom LLM-judge criteria   │ GEval ✓   │           │
  │ Hallucination detection     │     ✓     │           │
  │ Answer relevancy            │     ✓     │     ✓     │
  │ Faithfulness to context     │     ✓     │     ✓     │
  │ Context precision           │           │     ✓     │
  │ Context recall              │           │     ✓     │
  │ Deterministic checks        │ DAGMetric │           │
  │ Pytest / CI integration     │     ✓     │           │
  │ Batch / dataset eval        │           │     ✓     │
  │ Score dashboard             │ Confident │ Langfuse  │
  └─────────────────────────────┴───────────┴───────────┘
"""
