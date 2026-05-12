# ─── HireAi Backend — Developer Makefile ──────────────────────────────────────
#
# Run from the Backend/ directory.
# All flow targets require: pip install metaflow (already in requirements.txt)
#
# Usage examples:
#   make flow-score JOB_ID=acb7b34c-141d-4149-9f73-aac0e0c96d3b
#   make flow-score JOB_ID=<uuid> LIMIT=5
#   make flow-score-llm JOB_ID=<uuid> LIMIT=3    ← costs Azure credits

.PHONY: flow-score flow-score-llm flow-list flow-clean dev

# Default Python — override with: make flow-score PYTHON=python3.12
PYTHON ?= python

# ─── Metaflow Batch Scoring Targets ───────────────────────────────────────────

## Re-score candidates (rule-based only, zero API cost)
flow-score:
ifndef JOB_ID
	$(error JOB_ID is required: make flow-score JOB_ID=<uuid>)
endif
	$(PYTHON) flows/batch_scoring_flow.py run \
		--job_id $(JOB_ID) \
		--limit $(or $(LIMIT),20) \
		--use_llm false \
		--strong_threshold $(or $(STRONG),75.0) \
		--medium_threshold $(or $(MEDIUM),55.0)

## Re-score candidates with LLM scoring (uses Azure OpenAI credits)
flow-score-llm:
ifndef JOB_ID
	$(error JOB_ID is required: make flow-score-llm JOB_ID=<uuid>)
endif
	$(PYTHON) flows/batch_scoring_flow.py run \
		--job_id $(JOB_ID) \
		--limit $(or $(LIMIT),10) \
		--use_llm true \
		--strong_threshold $(or $(STRONG),75.0) \
		--medium_threshold $(or $(MEDIUM),55.0)

## List past BatchScoringFlow runs
flow-list:
	$(PYTHON) flows/batch_scoring_flow.py list

## Delete all local Metaflow state (run DB + artifacts) — irreversible
flow-clean:
	$(RM) -rf flows/.metaflow/

# ─── Dev Server ───────────────────────────────────────────────────────────────

## Start backend dev server
dev:
	uvicorn app.main:app --reload --port 8000
