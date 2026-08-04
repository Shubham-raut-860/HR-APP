# flows/ — Metaflow orchestration package for Jobora (local dev)
#
# Run flows from the Backend/ directory root:
#   python flows/batch_scoring_flow.py run --job_id <id> --limit 20
#
# All state (run DB, artifacts) is stored locally under flows/.metaflow/
# State is git-ignored via flows/.gitignore.
#
# See README-flows.md for full usage guide and future production notes.
