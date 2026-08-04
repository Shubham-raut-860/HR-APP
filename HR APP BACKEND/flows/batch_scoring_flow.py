"""
flows/batch_scoring_flow.py — Batch Candidate Scoring (Metaflow)
================================================================

RE-SCORES a batch of candidates for a given Job ID using the existing Jobora
hybrid scoring engine (rule-based + optional LLM). Results are written back to
the SQLite database and summarised in MLflow.

USAGE (from Backend/ directory):
    # Rule-based only (safe, no API cost):
    python flows/batch_scoring_flow.py run --job_id <uuid> --limit 20

    # With LLM scoring (uses Azure OpenAI credits):
    python flows/batch_scoring_flow.py run --job_id <uuid> --limit 10 --use_llm true

    # List past runs:
    python flows/batch_scoring_flow.py list

    # Inspect artifacts of the latest run:
    python -c "
    from metaflow import Flow
    run = Flow('BatchScoringFlow').latest_run
    print(run.data.summary)
    "

DESIGN NOTES:
- Steps use *synchronous* SQLAlchemy (sync URL, check_same_thread=False) to
  stay SQLite-safe. The async engine used by uvicorn is NOT imported here.
- configure_local_metaflow() and ensure_backend_on_path() MUST be called before
  any `from app.*` imports so subprocess sys.path is correct.
- The --use_llm flag defaults to False to avoid accidental API charges.
- MLflow logging is wrapped in try/except; a dead MLflow server won't fail the flow.

FUTURE / PRODUCTION:
- Replace local SQLite URL with postgresql+psycopg2://... in join step.
- Set METAFLOW_PROFILE to a cloud profile for S3 artifact storage.
- Trigger via Airflow BashOperator:
    python flows/batch_scoring_flow.py run --job_id {{ dag_run.conf['job_id'] }}
"""
from __future__ import annotations

# ── Bootstrap BEFORE any app imports ─────────────────────────────────────────
# These two calls must happen before `import metaflow` and before any
# `from app.*` import so that (a) Metaflow uses local filesystem storage and
# (b) each subprocess can resolve `app.*` regardless of cwd.
import os
import sys
import logging
import json
import time
from datetime import datetime, timezone

# Ensure Backend/ root is on sys.path for `from app.*` imports inside subprocesses
_FLOWS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_FLOWS_DIR)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# Scope Metaflow state to Backend/flows/.metaflow/
from flows.base import configure_local_metaflow, ensure_backend_on_path  # noqa: E402
configure_local_metaflow()
ensure_backend_on_path()

# ── Metaflow ────────────────────────────────────────────────────────────────
from metaflow import FlowSpec, step, Parameter, current  # noqa: E402

# ── Project imports (available after sys.path setup above) ──────────────────
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_BACKEND_ROOT, ".env"))  # load .env before settings

from app.config import settings  # noqa: E402
from app.models import Candidate, JobDescription, CandidateTag  # noqa: E402
from app.services.scoring_service import (  # noqa: E402
    compute_resume_score,
    assign_tag,
    get_score_breakdown,
    compute_resume_score_with_ai_override,
)
from flows._async_bridge import run_async  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ─── DB Helper ───────────────────────────────────────────────────────────────

def _make_sync_engine():
    """Create a synchronous SQLAlchemy engine from settings.DATABASE_URL.

    Strips async driver suffixes (+aiosqlite, +asyncpg) so the same URL string
    from .env works with the sync API used inside Metaflow step subprocesses.
    """
    from sqlalchemy import create_engine  # import here to avoid top-level cost

    sync_url = (
        settings.DATABASE_URL
        .replace("+aiosqlite", "")
        .replace("+asyncpg", "")
    )
    kwargs: dict = {}
    if sync_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(sync_url, **kwargs)


# ─── Flow ────────────────────────────────────────────────────────────────────

class BatchScoringFlow(FlowSpec):
    """Re-score candidates for a job using the Jobora hybrid scoring engine.

    Steps
    -----
    start            → fetch job + candidates from DB; fan-out
    score_candidate  → compute score for one candidate (foreach)
    join             → aggregate results; write to DB
    end              → log summary to MLflow; print report
    """

    # ── Parameters ───────────────────────────────────────────────────────────

    job_id = Parameter(
        "job_id",
        help="UUID of the JobDescription to score candidates for.",
        required=True,
        type=str,
    )
    limit = Parameter(
        "limit",
        help="Maximum number of candidates to score (0 = no limit).",
        default=20,
        type=int,
    )
    use_llm = Parameter(
        "use_llm",
        help="If true, call Azure OpenAI for AI-boosted scoring (costs credits).",
        default=False,
        type=bool,
    )
    strong_threshold = Parameter(
        "strong_threshold",
        help="Minimum score to tag a candidate as 'strong'.",
        default=75.0,
        type=float,
    )
    medium_threshold = Parameter(
        "medium_threshold",
        help="Minimum score to tag a candidate as 'medium'.",
        default=55.0,
        type=float,
    )
    triggered_by = Parameter(
        "triggered_by",
        help="Source of the run (e.g., 'manual', 'airflow', 'api').",
        default="manual",
        type=str,
    )

    # ── Steps ─────────────────────────────────────────────────────────────────

    @step
    def start(self):
        """Load job description and candidate list from the database.

        Stores:
          self.job   – dict of JobDescription fields needed for scoring
          self.candidates – list of dicts (one per candidate row)
        """
        from sqlalchemy.orm import Session  # local import keeps step lightweight

        engine = _make_sync_engine()
        with Session(engine) as session:
            job: JobDescription | None = session.get(JobDescription, self.job_id)
            if job is None:
                raise ValueError(f"JobDescription not found: {self.job_id}")

            # Store only the fields needed for scoring (keep artifact small)
            self.job = {
                "id": job.id,
                "title": job.title,
                "role": job.role,
                "experience_min": job.experience_min,
                "experience_max": job.experience_max,
                "must_have_skills": list(job.must_have_skills or []),
                "good_to_have_skills": list(job.good_to_have_skills or []),
                "description": job.description or "",
                "location": job.location or "",
                "education_requirement": job.education_requirement or "preferred",
                "embedding": job.embedding,  # may be None if not yet embedded
            }

            query = (
                session.query(Candidate)
                .filter(
                    Candidate.job_id == self.job_id,
                    Candidate.is_archived.is_(False),
                )
                .order_by(Candidate.created_at.desc())
            )
            if self.limit and self.limit > 0:
                query = query.limit(self.limit)

            rows = query.all()
            # Serialise to plain dicts — Metaflow artifacts must be picklable
            self.candidates = [
                {
                    "id": c.id,
                    "name": c.name or "Unknown",
                    "email": c.email or "",
                    "skills": list(c.skills or []),
                    "normalized_skills": list(c.normalized_skills or []),
                    "experience_years": float(c.experience_years or 0.0),
                    "location": c.location or "",
                    "education": list(c.education or []),
                    "projects": list(c.projects or []),
                    "work_experience": list(c.work_experience or []),
                    "skill_years": dict(c.skill_years or {}),
                    "embedding": c.embedding,
                }
                for c in rows
            ]

        logger.info(
            "BatchScoringFlow start | job_id=%s title=%s candidates=%d use_llm=%s",
            self.job_id, self.job["title"], len(self.candidates), self.use_llm,
        )
        self.next(self.score_candidate, foreach="candidates")

    @step
    def score_candidate(self):
        """Score a single candidate against the job description.

        This step runs in a separate subprocess for each candidate (Metaflow
        foreach pattern). Imports are kept inside the step body to avoid
        pickling issues with module-level objects.

        Stores:
          self.result – dict with candidate_id, resume_score, tag, breakdown,
                        component percentages, and elapsed_ms.
        """
        from app.services.scoring_service import (
            skill_match_score,
            experience_match_score,
            project_relevance_score,
            education_match_score,
            location_match_score,
            cosine_similarity,
        )

        candidate = self.input  # dict from start.candidates foreach
        job = self.job
        t0 = time.perf_counter()

        # ── Component scores (rule-based, synchronous) ────────────────────
        skill_pct = skill_match_score(
            candidate["normalized_skills"] or candidate["skills"],
            job["must_have_skills"],
            job["good_to_have_skills"],
        )
        exp_pct = experience_match_score(
            candidate["experience_years"],
            job["experience_min"],
            job["experience_max"],
        )
        proj_pct = project_relevance_score(
            candidate["projects"],
            job["must_have_skills"],
            job["good_to_have_skills"],
            candidate["experience_years"],
        )
        edu_pct = education_match_score(
            candidate["education"],
            candidate["experience_years"],
            job.get("description", ""),
            job["must_have_skills"],
            job.get("education_requirement", "preferred"),
        )
        loc_pct = location_match_score(
            candidate["location"],
            job.get("location", ""),
        )

        # Vector similarity (requires both embeddings to be present)
        vec_sim = 0.0
        if candidate["embedding"] and job["embedding"]:
            try:
                vec_sim = float(cosine_similarity(candidate["embedding"], job["embedding"]))
            except Exception:
                vec_sim = 0.0

        # ── AI Override (optional, costs Azure credits) ───────────────────
        ai_breakdown: dict = {}
        if self.use_llm:
            try:
                from app.services.gemini_service import score_resume_against_jd

                parsed_resume = {
                    "skills": candidate["skills"],
                    "normalized_skills": candidate["normalized_skills"],
                    "experience_years": candidate["experience_years"],
                    "location": candidate["location"],
                    "education": candidate["education"],
                    "projects": candidate["projects"],
                    "work_experience": candidate["work_experience"],
                    "skill_years": candidate["skill_years"],
                    "name": candidate["name"],
                }
                ai_breakdown = run_async(
                    score_resume_against_jd(
                        parsed_resume=parsed_resume,
                        job_title=job["title"],
                        exp_min=int(job["experience_min"]),
                        exp_max=int(job["experience_max"]),
                        must_have=job["must_have_skills"],
                        good_to_have=job["good_to_have_skills"],
                        description=job["description"],
                    )
                )
                # If AI returned overrides, apply them
                skill_pct = ai_breakdown.get("skill_match_pct", skill_pct)
                exp_pct = ai_breakdown.get("experience_match_pct", exp_pct)
                proj_pct = ai_breakdown.get("project_relevance_pct", proj_pct)
                edu_pct = ai_breakdown.get("education_match_pct", edu_pct)
            except Exception as exc:
                logger.warning(
                    "LLM scoring failed for candidate=%s, falling back to rule-based: %s",
                    candidate["id"], exc,
                )

        resume_score = compute_resume_score(
            skill_pct=skill_pct,
            experience_pct=exp_pct,
            project_pct=proj_pct,
            education_pct=edu_pct,
            vector_sim=vec_sim,
            location_pct=loc_pct,
            experience_years=candidate["experience_years"],
        )
        tag = assign_tag(
            resume_score,
            strong=self.strong_threshold,
            medium=self.medium_threshold,
        )
        breakdown = get_score_breakdown(
            skill_pct, exp_pct, proj_pct, edu_pct, vec_sim, loc_pct,
            candidate["experience_years"],
        )
        if ai_breakdown:
            breakdown["ai_score_used"] = True
            breakdown["ai_reasoning"] = ai_breakdown.get("reasoning", "")
            breakdown["matched_must_have"] = ai_breakdown.get("matched_must_have", [])
            breakdown["missing_must_have"] = ai_breakdown.get("missing_must_have", [])
        else:
            breakdown["ai_score_used"] = False

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        self.result = {
            "candidate_id": candidate["id"],
            "name": candidate["name"],
            "resume_score": resume_score,
            "tag": tag.value,
            "score_breakdown": breakdown,
            "skill_match_pct": skill_pct,
            "experience_match_pct": exp_pct,
            "project_relevance_pct": proj_pct,
            "education_match_pct": edu_pct,
            "vector_similarity": vec_sim,
            "location_match_pct": loc_pct,
            "elapsed_ms": elapsed_ms,
        }

        # Task 5.2 — structured per-candidate log line (picked up by uvicorn
        # when dispatched via API, and by terminal when run via CLI)
        logger.info(
            "scored | candidate_id=%s name=%r score=%.1f tag=%s ai=%s elapsed_ms=%.0f",
            candidate["id"], candidate["name"], resume_score,
            tag.value, self.use_llm, elapsed_ms,
        )

        self.next(self.join)

    @step
    def join(self, inputs):
        """Aggregate per-candidate results and write updated scores to DB.

        Uses a SYNCHRONOUS SQLAlchemy session (sync URL) for SQLite safety.
        The join step always runs in a single process — safe for WAL-mode SQLite.
        """
        from sqlalchemy.orm import Session
        from sqlalchemy import update as sa_update

        self.all_results = [inp.result for inp in inputs]
        # Carry job context forward to end step
        self.job = inputs[0].job  # all inputs share the same job dict

        if not self.all_results:
            logger.warning("join: no results to write — skipping DB update")
            self.next(self.end)
            return

        engine = _make_sync_engine()
        written = 0
        errors = 0
        with Session(engine) as session:
            for r in self.all_results:
                try:
                    session.execute(
                        sa_update(Candidate)
                        .where(Candidate.id == r["candidate_id"])
                        .values(
                            resume_score=r["resume_score"],
                            tag=CandidateTag(r["tag"]),
                            score_breakdown=r["score_breakdown"],
                            skill_match_pct=r["skill_match_pct"],
                            experience_match_pct=r["experience_match_pct"],
                            project_relevance_pct=r["project_relevance_pct"],
                            education_match_pct=r["education_match_pct"],
                            vector_similarity=r["vector_similarity"],
                            location_match_pct=r["location_match_pct"],
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
                    written += 1
                except Exception as exc:
                    errors += 1
                    logger.error(
                        "join: failed to update candidate_id=%s: %s",
                        r["candidate_id"], exc,
                    )
            session.commit()

        logger.info("join: wrote %d records, %d errors", written, errors)
        self.write_count = written
        self.error_count = errors
        self.next(self.end)

    @step
    def end(self):
        """Log a summary to MLflow and print a human-readable report.

        Task 5.1 — MLflow metric logging.
        MLflow is wrapped in try/except so a dead server doesn't fail the flow.
        """
        results = self.all_results
        n = len(results)

        if n == 0:
            self.summary = {"scored": 0, "strong": 0, "medium": 0, "reject": 0, "avg_score": 0.0}
            print("\n[BatchScoringFlow] No candidates scored.")
            return

        strong = sum(1 for r in results if r["tag"] == "strong")
        medium = sum(1 for r in results if r["tag"] == "medium")
        reject = n - strong - medium
        avg_score = round(sum(r["resume_score"] for r in results) / n, 2)
        avg_ms = round(sum(r["elapsed_ms"] for r in results) / n, 1)

        self.summary = {
            "job_id": self.job_id,
            "job_title": self.job.get("title", ""),
            "scored": n,
            "strong": strong,
            "medium": medium,
            "reject": reject,
            "avg_score": avg_score,
            "avg_elapsed_ms": avg_ms,
            "use_llm": self.use_llm,
            "db_writes": getattr(self, "write_count", n),
            "db_errors": getattr(self, "error_count", 0),
            "metaflow_run_id": current.run_id,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }

        # ── Task 5.1: MLflow summary metrics ─────────────────────────────
        try:
            import mlflow

            mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
            # Reuse the existing hr_evals experiment so all tracking is centralised
            mlflow.set_experiment(settings.MLFLOW_EXPERIMENT_NAME)

            with mlflow.start_run(run_name=f"BatchScore/{self.job_id[:8]}"):
                # Set tags for high-level identification in the run list
                mlflow.set_tags({
                    "job_id": self.job_id,
                    "triggered_by": self.triggered_by,
                    "orchestrator": "airflow" if "airflow" in self.triggered_by.lower() else "metaflow",
                })
                
                mlflow.log_params({
                    "job_id": self.job_id,
                    "job_title": self.job.get("title", ""),
                    "limit": self.limit,
                    "use_llm": str(self.use_llm),
                    "strong_threshold": self.strong_threshold,
                    "medium_threshold": self.medium_threshold,
                    "triggered_by": self.triggered_by,
                })
                mlflow.log_metrics({
                    "candidates_scored": float(n),
                    "strong_count": float(strong),
                    "medium_count": float(medium),
                    "reject_count": float(reject),
                    "avg_resume_score": avg_score,
                    "avg_scoring_ms": avg_ms,
                    "db_write_count": float(getattr(self, "write_count", n)),
                    "db_error_count": float(getattr(self, "error_count", 0)),
                })
                # Log the full per-candidate results as a JSON artifact
                mlflow.log_text(
                    json.dumps(results, indent=2),
                    artifact_file="per_candidate_scores.json",
                )
        except Exception as exc:
            logger.warning("MLflow logging skipped (server unreachable?): %s", exc)

        # ── Human-readable console report ─────────────────────────────────
        print(
            f"\n{'='*60}\n"
            f"  BatchScoringFlow Complete\n"
            f"  Job   : {self.job.get('title')} ({self.job_id})\n"
            f"  Scored: {n} candidates | use_llm={self.use_llm}\n"
            f"  Tags  : strong={strong}  medium={medium}  reject={reject}\n"
            f"  Avg score  : {avg_score:.1f} / 100\n"
            f"  Avg time   : {avg_ms:.0f} ms per candidate\n"
            f"  DB writes  : {getattr(self, 'write_count', n)} ok, "
            f"{getattr(self, 'error_count', 0)} errors\n"
            f"  Metaflow ID: {current.run_id}\n"
            f"{'='*60}"
        )


if __name__ == "__main__":
    BatchScoringFlow()
