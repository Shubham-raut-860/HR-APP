"""
Analytics router – dashboard metrics, ranking, skill gap
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import List
import io
import asyncio
import logging
from app.database import get_db
from app.models import User, Candidate, JobDescription, CandidateTag, UserRole
from app.schemas import AnalyticsSummary, SkillGapItem, CandidateRankRow, MessageResponse
from app.services.auth_service import require_hr, log_action
from app.services import export_service
from app.services import scoring_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])
logger = logging.getLogger(__name__)


@router.get("/metrics/untagged")
async def get_untagged_metrics(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    from sqlalchemy import func
    query = select(func.count(Candidate.id)).where(
        Candidate.tag.is_(None),
        Candidate.job_id.isnot(None),
        Candidate.is_archived == False
    )
    if user.role != UserRole.admin:
        query = query.join(JobDescription, Candidate.job_id == JobDescription.id).where(JobDescription.created_by == user.id)
    res = await db.execute(query)
    return {"untagged_count": res.scalar_one() or 0}


# ─── Internal ownership helper ────────────────────────────────────────────────

async def _assert_job_owner(job_id: str, user: User, db: AsyncSession) -> JobDescription:
    """Fetch a job and raise 403/404 if the requesting HR user doesn't own it."""
    jd = (await db.execute(
        select(JobDescription).where(JobDescription.id == job_id)
    )).scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    if user.role != UserRole.admin and jd.created_by != user.id:
        raise HTTPException(
            status_code=403, detail="You do not have access to analytics for this job")
    return jd


# ─── Shared summary computation (SQL aggregation) ────────────────────────────

async def _compute_summary(job_id: str, db: AsyncSession) -> AnalyticsSummary:
    """Compute analytics summary using SQL aggregation.

    BUG-4 FIX: The original implementation fetched every Candidate row into
    Python (including embedding JSON, score_breakdown blobs, work_experience)
    just to count tags via `sum(1 for c in candidates if c.tag == ...)`. For
    5,000 candidates this transmitted megabytes of JSON for what is essentially
    a SELECT COUNT(*) GROUP BY query. Replaced with pure SQL aggregation.
    """
    from sqlalchemy import func, case, or_

    archive_filter = or_(Candidate.is_archived == False, Candidate.is_archived.is_(None))

    # ── Single aggregate query for counts ──────────────────────────────────────
    agg = (await db.execute(
        select(
            func.count(Candidate.id).label("total"),
            func.sum(case((Candidate.tag == CandidateTag.strong, 1), else_=0)).label("strong"),
            func.sum(case((Candidate.tag == CandidateTag.medium, 1), else_=0)).label("medium"),
            func.sum(case((Candidate.tag == CandidateTag.reject,  1), else_=0)).label("reject"),
            func.sum(case((Candidate.quiz_score.isnot(None),       1), else_=0)).label("quiz_taken"),
            func.sum(case((Candidate.final_score.isnot(None),      1), else_=0)).label("ranked"),
            func.avg(case(
                (Candidate.resume_score > 0, Candidate.resume_score), else_=None
            )).label("avg_resume"),
            func.avg(Candidate.quiz_pct).label("avg_quiz_pct"),
            func.avg(Candidate.final_score).label("avg_final"),
            func.sum(case((Candidate.passed == True,  1), else_=0)).label("pass_count"),
            func.sum(case((Candidate.passed == False, 1), else_=0)).label("fail_count"),
        ).where(Candidate.job_id == job_id, archive_filter)
    )).one()

    total = agg.total or 0
    if not total:
        return AnalyticsSummary(
            total_applicants=0, shortlisted_count=0, shortlisted_pct=0,
            strong_count=0, medium_count=0, reject_count=0,
            quiz_taken_count=0, ranked_count=0,
            avg_resume_score=0, avg_quiz_score=None, avg_quiz_pct=None, avg_final_score=None,
            pass_count=0, fail_count=0,
        )

    strong = int(agg.strong or 0)
    medium = int(agg.medium or 0)
    shortlisted = strong + medium

    return AnalyticsSummary(
        total_applicants=total,
        shortlisted_count=shortlisted,
        shortlisted_pct=round(shortlisted / total * 100, 2) if total else 0,
        strong_count=strong,
        medium_count=medium,
        reject_count=int(agg.reject or 0),
        quiz_taken_count=int(agg.quiz_taken or 0),
        ranked_count=int(agg.ranked or 0),
        avg_resume_score=round(float(agg.avg_resume), 2) if agg.avg_resume is not None else 0,
        avg_quiz_score=round(float(agg.avg_quiz_pct), 2) if agg.avg_quiz_pct is not None else None,
        avg_quiz_pct=round(float(agg.avg_quiz_pct), 2) if agg.avg_quiz_pct is not None else None,
        avg_final_score=round(float(agg.avg_final), 2) if agg.avg_final is not None else None,
        pass_count=int(agg.pass_count or 0),
        fail_count=int(agg.fail_count or 0),
    )


@router.get("/summary/{job_id}", response_model=AnalyticsSummary)
async def get_summary(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    await _assert_job_owner(job_id, user, db)
    return await _compute_summary(job_id, db)


@router.get("/rankings/{job_id}", response_model=List[CandidateRankRow])
async def get_rankings(
    job_id: str,
    recalculate: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    await _assert_job_owner(job_id, user, db)

    if recalculate:
        # BUG-15 FIX: Use SQL ROW_NUMBER() window function instead of loading
        # all candidates into Python, sorting, and running an N+1 update loop.
        await db.execute(text("""
            UPDATE candidates SET rank = (
                SELECT rn 
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               ORDER BY COALESCE(final_score, resume_score, 0) DESC
                           ) AS rn
                    FROM candidates
                    WHERE job_id = :job_id AND is_archived IS FALSE
                ) sub
                WHERE sub.id = candidates.id
            )
            WHERE job_id = :job_id AND is_archived IS FALSE
        """), {"job_id": job_id})
        await db.flush()
        await db.commit()

    res = await db.execute(
        select(Candidate).where(
            Candidate.job_id == job_id,
            Candidate.is_archived == False
        )
        .order_by(Candidate.rank.asc().nullslast(), Candidate.final_score.desc().nullslast(), Candidate.resume_score.desc())
    )
    candidates = res.scalars().all()

    return [
        CandidateRankRow(
            rank=c.rank or (idx + 1),
            candidate_id=c.id,
            name=c.name,
            email=c.email,
            tag=c.tag.value if c.tag else None,
            resume_score=c.resume_score,
            quiz_score=c.quiz_score,
            quiz_max=c.quiz_max,
            quiz_pct=c.quiz_pct,
            final_score=c.final_score,
            passed=c.passed,
        )
        for idx, c in enumerate(candidates)
    ]


@router.get("/skill-gap/{job_id}", response_model=List[SkillGapItem])
async def get_skill_gap(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    jd = await _assert_job_owner(job_id, user, db)

    # BUG-NEW-5 FIX: select only the skills column — avoids loading embedding blobs
    # and score_breakdown JSON into Python for a pure skill-count operation.
    rows = (await db.execute(
        select(Candidate.normalized_skills).where(
            Candidate.job_id == job_id,
            Candidate.is_archived == False,
        )
    )).all()
    total = len(rows)

    if not total:
        return []

    all_required = (
        [(s, True) for s in (jd.must_have_skills or [])] +
        [(s, False) for s in (jd.good_to_have_skills or [])]
    )

    candidate_skills_lists = [
        list(r[0] or [])
        for r in rows
    ]

    result = []
    for skill, required in all_required:
        match_count = sum(
            1 for c_skills in candidate_skills_lists
            if scoring_service.semantic_skill_match(skill, c_skills)
        )
        pct = round(match_count / total * 100, 2)
        result.append(SkillGapItem(
            skill=skill,
            required=required,
            candidate_match_pct=pct,
            gap_pct=round(100 - pct, 2),
        ))

    return sorted(result, key=lambda x: x.gap_pct, reverse=True)


@router.get("/export/excel/{job_id}")
async def export_excel(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    jd = await _assert_job_owner(job_id, user, db)
    title = jd.title

    c_res = await db.execute(
        select(Candidate).where(
            Candidate.job_id == job_id,
            Candidate.is_archived == False,
        ).order_by(Candidate.rank.asc().nullslast())
    )
    candidates = [
        {k: getattr(c, k) for k in [
            "rank", "name", "email", "tag", "normalized_skills",
            "experience_years", "skill_match_pct", "experience_match_pct",
            "resume_score", "quiz_score", "final_score", "passed",
        ]}
        for c in c_res.scalars().all()
    ]
    for c in candidates:
        if c["tag"]:
            c["tag"] = c["tag"].value

    try:
        content = await asyncio.to_thread(export_service.generate_excel_report, candidates, title)
    except Exception as exc:
        logger.exception("Excel export failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc

    await log_action(db, user.id, "EXPORT_EXCEL", "job_description", job_id)
    await db.commit()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{title}_report.xlsx"'},
    )


@router.get("/export/pdf/{job_id}")
async def export_pdf(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    jd = await _assert_job_owner(job_id, user, db)
    title = jd.title

    # BUG-14 FIX: Reuse _compute_summary instead of copy-pasting 20 lines of math.
    summary = await _compute_summary(job_id, db)

    c_res = await db.execute(
        select(Candidate).where(
            Candidate.job_id == job_id,
            Candidate.is_archived == False,
        ).order_by(Candidate.rank.asc().nullslast())
    )
    candidates = [
        {k: getattr(c, k) for k in [
            "rank", "name", "email", "tag", "resume_score", "quiz_score", "final_score", "passed",
        ]}
        for c in c_res.scalars().all()
    ]
    for c in candidates:
        if c["tag"]:
            c["tag"] = c["tag"].value

    try:
        content = await asyncio.to_thread(
            export_service.generate_pdf_report, candidates, title, summary.model_dump()
        )
    except Exception as exc:
        logger.exception("PDF export failed")
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc

    await log_action(db, user.id, "EXPORT_PDF", "job_description", job_id)
    await db.commit()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{title}_report.pdf"'},
    )


@router.post("/rank/{job_id}", response_model=MessageResponse)
async def calculate_rankings(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """Recalculate rankings and final scores for all candidates in a job."""
    await _assert_job_owner(job_id, user, db)

    # BUG-15 FIX: Use SQL window function for O(1) ranking in the DB
    # instead of loading all candidates into Python memory.
    result = await db.execute(text("""
        UPDATE candidates SET rank = (
            SELECT rn 
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           ORDER BY COALESCE(final_score, resume_score, 0) DESC
                       ) AS rn
                FROM candidates
                WHERE job_id = :job_id AND is_archived IS FALSE
            ) sub
            WHERE sub.id = candidates.id
        )
        WHERE job_id = :job_id AND is_archived IS FALSE
    """), {"job_id": job_id})
    updated_count = result.rowcount

    await db.flush()
    await log_action(db, user.id, "CALCULATE_RANKINGS", "job_description", job_id)
    await db.commit()
    return {"message": f"Rankings updated for {updated_count} candidates"}


# ─── MLflow Telemetry API ──────────────────────────────────────────────────────


@router.get("/mlflow/runs")
async def get_mlflow_runs(
    operation: str | None = None,
    limit: int = 20,
    user: User = Depends(require_hr),
):
    """
    Return recent MLflow eval runs for the dashboard.

    Query params:
      - operation: filter by task tag (e.g. resume_parsing, resume_scoring, jd_generation)
      - limit: max rows to return (default 20)
    """
    try:
        import mlflow
        from app.config import settings
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)

        filter_str = f"tags.task = '{operation}'" if operation else ""
        runs = mlflow.search_runs(
            experiment_names=[settings.MLFLOW_EXPERIMENT_NAME],
            filter_string=filter_str,
            max_results=limit,
            order_by=["start_time DESC"],
            output_format="list",
        )
        return [
            {
                "run_id":     r.info.run_id,
                "run_name":   r.info.run_name,
                "status":     r.info.status,
                "start_time": r.info.start_time,
                "end_time":   r.info.end_time,
                "tags":       r.data.tags,
                "metrics":    r.data.metrics,
                "params":     r.data.params,
            }
            for r in runs
        ]
    except Exception as exc:
        logger.exception("MLflow tracking server unavailable")
        raise HTTPException(
            status_code=503,
            detail="An internal error occurred.",
        )


class EvalRunRequest(BaseModel):
    operation: str  # 'resume_parsing' | 'resume_scoring' | 'jd_generation'
    samples: list[dict]  # [{"inputs": "...", "outputs": "...", "ground_truth": "..."}]
    run_name: str | None = None


@router.post("/mlflow/evaluate")
async def trigger_mlflow_evaluation(
    body: EvalRunRequest,
    user: User = Depends(require_hr),
):
    """
    Trigger an on-demand MLflow Evaluation Run.

    Populates: Evaluation Runs, Judges, Datasets tabs in MLflow UI.

    Body:
      - operation:    'resume_parsing' | 'resume_scoring' | 'jd_generation'
      - samples:      list of {inputs, outputs, ground_truth} dicts
      - run_name:     optional label for this eval run
    """
    if len(body.samples) > 50:
        raise HTTPException(
            status_code=400,
            detail="Maximum 50 samples allowed per evaluation run."
        )
    try:
        import asyncio
        from app.services.mlflow_service import run_mlflow_evaluation
        results = await asyncio.to_thread(
            run_mlflow_evaluation,
            operation=body.operation,
            eval_data=body.samples,
            run_name=body.run_name or f"eval_{body.operation}",
        )
        if results:
            return {
                "status":      "ok",
                "operation":   body.operation,
                "sample_count": len(body.samples),
                "metrics":     results.metrics if hasattr(results, "metrics") else {},
            }
        return {"status": "ok", "operation": body.operation, "metrics": {}}
    except Exception as exc:
        logger.exception("MLflow evaluation failed")
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred.",
        )
