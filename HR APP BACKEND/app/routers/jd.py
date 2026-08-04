"""
JD router Ã¢â‚¬â€œ create, generate, list, get, update, delete
"""
from app.models import NotificationType
from app.services.notification_service import push_to_all_candidates
from app.services.auth_service import require_hr, log_action
from app.services.adk_shadow_service import schedule_adk_shadow_observation
from app.limiter import limiter
from app.config import settings
from app.schemas import JDCreate, JDOut, JDGenerateRequest, MessageResponse
from app.models import User, JobDescription, UserRole, BulkUploadJob
from app.database import AsyncSessionLocal, get_db
from typing import List, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Request
import os
import hashlib
import asyncio
import logging
import re
from uuid import uuid4
from datetime import datetime, timezone
from importlib import import_module

logger = logging.getLogger(__name__)
try:
    _JD_UPDATE_EMBED_TIMEOUT_S = max(0.5, float(os.getenv("JD_UPDATE_EMBED_TIMEOUT_S", "10.0")))
except (TypeError, ValueError):
    _JD_UPDATE_EMBED_TIMEOUT_S = 10.0
_JD_UPDATE_EMBED_FORCE_ON_SQLITE = str(
    os.getenv("JD_UPDATE_EMBED_FORCE_ON_SQLITE", "")
).strip().lower() in {"1", "true", "yes", "on"}

router = APIRouter(prefix="/jd", tags=["Job Descriptions"])
JD_ALLOWED_EXTENSIONS = set(settings.allowed_extensions_list) | {
    ".txt",
    ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".gif",
}
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


def _gemini_service():
    return import_module("app.services.gemini_service")


def _cache_service():
    return import_module("app.services.cache_service")


def _file_service():
    return import_module("app.services.file_service")


def _harness_agent_client():
    return import_module("app.services.harness_agent_client")


def _is_harness_or_timeout_error(exc: Exception) -> bool:
    return isinstance(exc, asyncio.TimeoutError) or exc.__class__.__name__ == "HarnessAgentError"


def _resolve_jd_file_hash(raw_text: str, provided_hash: str | None) -> str:
    normalized = str(provided_hash or "").strip().lower()
    if normalized and _HEX_64_RE.fullmatch(normalized):
        return normalized
    if normalized:
        logger.warning("Ignoring invalid JD file_hash format during create: %s", normalized[:16])
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


async def _fanout_job_posted_notification_async(
    *,
    title: str,
    message: str,
    related_id: str,
    retries: int = 3,
) -> None:
    for attempt in range(1, retries + 1):
        async with AsyncSessionLocal() as notif_db:
            try:
                await push_to_all_candidates(
                    notif_db,
                    title=title,
                    message=message,
                    ntype=NotificationType.job_posted,
                    related_id=related_id,
                )
                await notif_db.commit()
                return
            except Exception as exc:
                await notif_db.rollback()
                if attempt >= retries:
                    logger.exception(
                        "Candidate notification fanout failed permanently for related_id=%s after %s attempts",
                        related_id,
                        attempt,
                    )
                    return
                logger.warning(
                    "Candidate notification fanout retry %s/%s for related_id=%s due to error=%s",
                    attempt,
                    retries,
                    related_id,
                    exc,
                )
        await asyncio.sleep(min(2.0, 0.4 * attempt))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _update_jd_bulk_run_status(
    run_id: str,
    *,
    status: str,
    processed: int | None = None,
    failed: int | None = None,
    details: dict[str, Any] | None = None,
    error_summary: dict[str, Any] | None = None,
) -> None:
    async with AsyncSessionLocal() as s:
        row = await s.get(BulkUploadJob, run_id)
        if not row:
            return
        row.status = status
        if processed is not None:
            row.processed = int(processed)
        if failed is not None:
            row.failed = int(failed)
        if details is not None:
            row.details = details
        if error_summary is not None:
            row.error_summary = error_summary
        await s.commit()


async def _run_jd_bulk_from_documents_job(
    *,
    run_id: str,
    files_payload: list[dict[str, Any]],
    auth_header: str | None,
    requested_by: str,
) -> None:
    job_started = asyncio.get_event_loop().time()

    async def _execute() -> None:
        read_failures: list[dict[str, Any]] = []
        success_records: list[dict[str, Any]] = []
        posted_jobs_for_notification: list[JobDescription] = []
        parse_sem = asyncio.Semaphore(5)
        embed_sem = asyncio.Semaphore(5)

        async with AsyncSessionLocal() as db:
            try:
                valid: list[tuple[str, dict[str, Any], str, bytes]] = []

                async def _extract_and_parse_one(fname: str, content: bytes) -> tuple[dict[str, Any], str]:
                    async with parse_sem:
                        text = await _file_service().extract_text_from_bytes(fname, content)
                        if not text.strip():
                            raise ValueError("Could not extract any text from the document")
                        parsed_job = await _run_jd_parser_with_fallback(
                            doc_text=text,
                            auth_header=auth_header,
                        )
                        return parsed_job, text

                for payload in files_payload:
                    fname = str(payload.get("filename") or "document.pdf")
                    content = payload.get("content") or b""
                    try:
                        result, raw_text = await _extract_and_parse_one(fname, content)
                        rt = (
                            f"{result.get('title', '')}\n{result.get('role', '')}\n"
                            f"{result.get('description', '')}\n"
                            f"Must Have: {', '.join(result.get('must_have_skills') or [])}\n"
                            f"Good To Have: {', '.join(result.get('good_to_have_skills') or [])}"
                        )
                        valid.append((fname, result, rt, content))
                    except Exception:
                        logger.exception("JD bulk async parse failed for %s", fname)
                        read_failures.append({"filename": fname, "error": "Failed to parse document."})

                async def _embed(raw_text: str) -> list:
                    async with embed_sem:
                        return await _run_jd_embedding_with_fallback(raw_text, auth_header)

                embed_results = await asyncio.gather(
                    *[_embed(rt) for _, _, rt, _ in valid],
                    return_exceptions=True,
                ) if valid else []

                for (fname, ai_data, raw_text, content), embedding in zip(valid, embed_results):
                    if isinstance(embedding, Exception):
                        read_failures.append({"filename": fname, "error": f"Embedding failed: {embedding}"})
                        continue

                    title = (ai_data.get("title") or "").strip() or os.path.splitext(fname)[0]
                    role = (ai_data.get("role") or "").strip() or title
                    exp_min, exp_max = _normalize_experience_bounds(
                        ai_data.get("experience_min"),
                        ai_data.get("experience_max"),
                    )

                    jd = JobDescription(
                        title=title,
                        role=role,
                        description=ai_data.get("description") or "",
                        must_have_skills=ai_data.get("must_have_skills") or [],
                        good_to_have_skills=ai_data.get("good_to_have_skills") or [],
                        experience_min=exp_min,
                        experience_max=exp_max,
                        location=ai_data.get("location") or "Remote",
                        employment_type=ai_data.get("employment_type") or "Full-time",
                        salary_range=None,
                        resume_weight=50,
                        quiz_weight=50,
                        pass_threshold=60,
                        file_hash=hashlib.sha256(content).hexdigest(),
                        raw_text=raw_text,
                        embedding=embedding,
                        created_by=requested_by,
                    )
                    db.add(jd)
                    await db.flush()
                    await log_action(db, requested_by, "CREATE_JD", "job_description", jd.id)
                    posted_jobs_for_notification.append(jd)
                    success_records.append(
                        {
                            "filename": fname,
                            "job_id": jd.id,
                            "title": jd.title,
                            "role": jd.role,
                            "location": jd.location,
                        }
                    )

                await db.commit()

                if posted_jobs_for_notification and not settings.DATABASE_URL.startswith("sqlite"):
                    if len(posted_jobs_for_notification) == 1:
                        only = posted_jobs_for_notification[0]
                        asyncio.create_task(
                            _fanout_job_posted_notification_async(
                                title=f"New Job Posted: {only.title}",
                                message=f"{only.role} - {only.location or 'Remote'} - {only.experience_min}-{only.experience_max} yrs exp.",
                                related_id=only.id,
                            )
                        )
                    else:
                        preview = ", ".join(jd.title for jd in posted_jobs_for_notification[:3])
                        more = len(posted_jobs_for_notification) - 3
                        suffix = f" and {more} more" if more > 0 else ""
                        asyncio.create_task(
                            _fanout_job_posted_notification_async(
                                title=f"{len(posted_jobs_for_notification)} New Jobs Posted",
                                message=f"{preview}{suffix}. Open Candidate Portal to view and apply.",
                                related_id=posted_jobs_for_notification[0].id,
                            )
                        )

                await _update_jd_bulk_run_status(
                    run_id,
                    status="completed",
                    processed=len(success_records),
                    failed=len(read_failures),
                    details={
                        "run_type": "jd_bulk_documents",
                        "finished_at": _utc_now_iso(),
                        "duration_ms": round((asyncio.get_event_loop().time() - job_started) * 1000.0, 2),
                        "success": success_records,
                        "failed": read_failures,
                        "success_count": len(success_records),
                        "failed_count": len(read_failures),
                    },
                )
            except Exception as exc:
                logger.exception("JD bulk async run failed run_id=%s", run_id)
                await db.rollback()
                await _update_jd_bulk_run_status(
                    run_id,
                    status="failed",
                    processed=len(success_records),
                    failed=max(1, len(read_failures)),
                    error_summary={"error": str(exc)},
                    details={
                        "run_type": "jd_bulk_documents",
                        "failed": read_failures,
                        "finished_at": _utc_now_iso(),
                        "duration_ms": round((asyncio.get_event_loop().time() - job_started) * 1000.0, 2),
                    },
                )

    await _update_jd_bulk_run_status(
        run_id,
        status="running",
        details={"run_type": "jd_bulk_documents", "started_at": _utc_now_iso()},
    )
    try:
        await asyncio.wait_for(_execute(), timeout=300.0)
    except asyncio.TimeoutError:
        logger.warning("JD bulk async run timed out run_id=%s", run_id)
        await _update_jd_bulk_run_status(
            run_id,
            status="failed",
            processed=0,
            failed=max(1, len(files_payload)),
            error_summary={"error": "timeout"},
            details={
                "run_type": "jd_bulk_documents",
                "finished_at": _utc_now_iso(),
                "duration_ms": round((asyncio.get_event_loop().time() - job_started) * 1000.0, 2),
            },
        )


def _normalize_experience_bounds(
    experience_min: int | float | str | None,
    experience_max: int | float | str | None,
) -> tuple[int, int]:
    try:
        exp_min = int(experience_min or 0)
    except (TypeError, ValueError):
        exp_min = 0
    try:
        exp_max = int(experience_max or 5)
    except (TypeError, ValueError):
        exp_max = 5

    exp_min = max(0, exp_min)
    exp_max = max(0, exp_max)
    if exp_max < exp_min:
        exp_max = exp_min
    return exp_min, exp_max


def _safe_skill_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        skill = str(item or "").strip()
        if not skill:
            continue
        key = skill.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(skill)
    return out


def _build_local_jd_fallback(
    *,
    role: str,
    experience_min: int,
    experience_max: int,
    location: str | None,
    additional_context: str | None,
) -> dict:
    role_clean = (role or "Professional").strip() or "Professional"
    role_title = role_clean.title()
    loc = (location or "Remote").strip() or "Remote"
    context_line = f" Context: {additional_context.strip()}" if (additional_context or "").strip() else ""
    description = (
        f"We are hiring a {role_title} with {experience_min}-{experience_max} years of experience. "
        f"The role is based in {loc}. You will design, build, and improve production systems, "
        f"collaborate across teams, and deliver reliable outcomes with strong ownership.{context_line}"
    )
    return {
        "title": role_title,
        "role": role_clean,
        "location": loc,
        "experience_min": experience_min,
        "experience_max": experience_max,
        "must_have_skills": [],
        "good_to_have_skills": [],
        "description": description,
        "education_requirement": "none",
    }


def _fast_parse_jd_text(doc_text: str) -> dict:
    lines = [ln.strip() for ln in (doc_text or "").splitlines() if ln.strip()]
    title = lines[0][:120] if lines else "Untitled Role"
    text_lower = (doc_text or "").lower()
    must: list[str] = []
    good: list[str] = []
    for marker, bucket in (("must have", must), ("good to have", good)):
        idx = text_lower.find(marker)
        if idx >= 0:
            snippet = doc_text[idx: idx + 320]
            tail = snippet.split(":", 1)[-1]
            for tok in [t.strip(" .,\n\t-") for t in tail.replace("/", ",").split(",")]:
                if tok and len(tok) > 1:
                    bucket.append(tok)
    return {
        "title": title,
        "role": title,
        "description": (doc_text or "")[:4000],
        "must_have_skills": must[:25],
        "good_to_have_skills": good[:25],
        "experience_min": 0,
        "experience_max": 8,
        "location": "Remote",
    }


def _normalize_generated_jd(
    *,
    ai_data: dict | None,
    role: str,
    experience_min: int,
    experience_max: int,
    location: str | None,
    additional_context: str | None,
) -> dict:
    fallback = _build_local_jd_fallback(
        role=role,
        experience_min=experience_min,
        experience_max=experience_max,
        location=location,
        additional_context=additional_context,
    )
    src = ai_data if isinstance(ai_data, dict) else {}

    title = str(src.get("title") or fallback["title"]).strip() or fallback["title"]
    role_value = str(src.get("role") or role or title).strip() or fallback["role"]
    loc = str(src.get("location") or location or fallback["location"]).strip() or fallback["location"]
    desc = str(src.get("description") or "").strip()
    if not desc:
        desc = str(fallback["description"])

    must_have = _safe_skill_list(src.get("must_have_skills"))
    good_to_have = _safe_skill_list(src.get("good_to_have_skills"))
    education_requirement = str(src.get("education_requirement") or "none").strip() or "none"

    return {
        "title": title,
        "role": role_value,
        "location": loc,
        "experience_min": experience_min,
        "experience_max": experience_max,
        "must_have_skills": must_have,
        "good_to_have_skills": good_to_have,
        "description": desc,
        "education_requirement": education_requirement,
    }


async def _run_jd_parser_with_fallback(
    *,
    doc_text: str,
    auth_header: str | None = None,
) -> dict:
    gemini_service = _gemini_service()
    harness_agent_client = _harness_agent_client()
    parser_timeout_s = min(30.0, max(10.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 1.5))
    if bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE and not gemini_service.is_realtime_ai_available()):
        logger.warning("JD parser: AI backend unavailable; using fast local parser fallback.")
        return _fast_parse_jd_text(doc_text)
    try:
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "jd_parser",
                {"doc_text": doc_text},
                auth_header,
                # Keep parser attempts bounded so /jd/from-document can fall back
                # before frontend request timeouts are hit.
                timeout_s=parser_timeout_s,
            ),
            timeout=parser_timeout_s,
        )
        if isinstance(result, dict) and isinstance(result.get("parsed_job"), dict):
            return result["parsed_job"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback jd_parser failed, using direct parser: %s", runtime_exc)
        try:
            return await asyncio.wait_for(
                gemini_service.parse_jd_from_document(doc_text),
                timeout=parser_timeout_s,
            )
        except Exception as direct_exc:
            logger.warning("Direct JD parser failed; using fast local parser fallback: %s", direct_exc)
            return _fast_parse_jd_text(doc_text)


async def _run_jd_embedding_with_fallback(raw_text: str, auth_header: str | None = None) -> list:
    gemini_service = _gemini_service()
    harness_agent_client = _harness_agent_client()
    if bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE and not gemini_service.is_realtime_ai_available()):
        logger.warning("JD embedding: AI backend unavailable; skipping embedding and cache lookup.")
        return []
    embedding_timeout_s = min(30.0, max(12.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 1.75))
    try:
        result = await asyncio.wait_for(
            harness_agent_client.run_agent(
                "embedding",
                {"text": raw_text},
                auth_header,
                # Embeddings are on the critical path for JD create/update calls.
                # Bound harness wait time to avoid long UI hangs before fallback.
                timeout_s=embedding_timeout_s,
            ),
            timeout=embedding_timeout_s,
        )
        if isinstance(result, dict):
            emb = result.get("embedding")
            if isinstance(emb, list):
                return emb
        return result if isinstance(result, list) else []
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback jd_embedding failed, using direct embedding: %s", runtime_exc)
        return await asyncio.wait_for(
            gemini_service.get_embedding(raw_text),
            timeout=embedding_timeout_s,
        )


async def _generate_and_store_jd_embedding(
    jd_id: str,
    jd_text: str,
    auth_header: str | None = None,
) -> None:
    try:
        embedding = await _run_jd_embedding_with_fallback(
            jd_text,
            auth_header,
        )
    except Exception as embed_exc:
        logger.warning("Background JD embedding failed for jd_id=%s: %s", jd_id, embed_exc)
        return

    async with AsyncSessionLocal() as embedding_db:
        try:
            jd = await embedding_db.get(JobDescription, jd_id)
            if jd is None:
                logger.warning("Background JD embedding skipped; job not found jd_id=%s", jd_id)
                return
            jd.embedding = embedding
            await embedding_db.commit()
            logger.info("Background JD embedding stored for jd_id=%s", jd_id)
        except Exception as store_exc:
            await embedding_db.rollback()
            logger.warning("Background JD embedding store failed for jd_id=%s: %s", jd_id, store_exc)


async def _run_jd_generation_with_fallback(
    *,
    role: str,
    experience_min: int,
    experience_max: int,
    location: str | None,
    additional_context: str | None,
    auth_header: str | None = None,
) -> dict:
    gemini_service = _gemini_service()
    harness_agent_client = _harness_agent_client()
    jd_generate_timeout_s = min(18.0, max(8.0, float(settings.AI_REQUEST_TIMEOUT_SECONDS) * 1.35))
    if bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE and not gemini_service.is_realtime_ai_available()):
        logger.warning("JD generation: AI backend unavailable; using local template fallback immediately.")
        return _build_local_jd_fallback(
            role=role,
            experience_min=experience_min,
            experience_max=experience_max,
            location=location,
            additional_context=additional_context,
        )
    try:
        result = await harness_agent_client.run_agent(
            "jd_generator",
            {
                "role": role,
                "experience_min": experience_min,
                "experience_max": experience_max,
                "location": location,
                "additional_context": additional_context,
            },
            auth_header,
            # Keep backend response under frontend /jd/generate timeout budget.
            # If harness is slow/unavailable, fail fast and use direct/local fallback.
            timeout_s=jd_generate_timeout_s,
        )
        if isinstance(result, dict) and isinstance(result.get("jd_data"), dict):
            return result["jd_data"]
        return result if isinstance(result, dict) else {}
    except Exception as runtime_exc:
        if not _is_harness_or_timeout_error(runtime_exc):
            raise
        logger.warning("Harness fallback jd_generator failed, using direct generator: %s", runtime_exc)
        try:
            return await asyncio.wait_for(
                gemini_service.generate_jd(
                    role=role,
                    exp_min=experience_min,
                    exp_max=experience_max,
                    location=location or "Remote",
                    context=additional_context or "",
                ),
                timeout=jd_generate_timeout_s,
            )
        except Exception as direct_exc:
            logger.exception(
                "Direct JD generation failed after harness fallback for role=%s. Using local template. Error=%s",
                role,
                direct_exc,
            )
            return _build_local_jd_fallback(
                role=role,
                experience_min=experience_min,
                experience_max=experience_max,
                location=location,
                additional_context=additional_context,
            )


@router.post("/from-document")
async def generate_jd_from_document(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    allowed = JD_ALLOWED_EXTENSIONS
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Accepted: {', '.join(sorted(allowed))}.",
        )

    _buf = bytearray()
    while _chunk := await file.read(1024 * 1024):
        _buf.extend(_chunk)
        if len(_buf) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File exceeds 5 MB limit.")
    content = bytes(_buf)
    file_hash = hashlib.sha256(content).hexdigest()

    existing = (await db.execute(
        select(JobDescription).where(JobDescription.file_hash == file_hash, JobDescription.is_active == True)
    )).scalar_one_or_none()

    if existing:
        return {
            "title": existing.title,
            "role": existing.role,
            "description": existing.description or "",
            "must_have_skills": existing.must_have_skills or [],
            "good_to_have_skills": existing.good_to_have_skills or [],
            "experience_min": existing.experience_min,
            "experience_max": existing.experience_max,
            "location": existing.location or "Remote",
            "employment_type": existing.employment_type or "Full-time",
            "_cached": True,
            "_cached_jd_id": existing.id,
        }

    text = await _file_service().extract_text_from_bytes(file.filename or "jd", content)
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract any text from the uploaded file.",
        )

    try:
        ai_data = await _run_jd_parser_with_fallback(
            doc_text=text,
            auth_header=request.headers.get("authorization"),
        )
    except Exception as e:
        logger.exception("JD extraction from document failed for file=%s", file.filename)
        raise HTTPException(status_code=500, detail="An internal error occurred.") from e

    ai_data["_file_hash"] = file_hash
    ai_data["_raw_text"] = text[:20000]
    exp_min, exp_max = _normalize_experience_bounds(
        ai_data.get("experience_min"),
        ai_data.get("experience_max"),
    )

    # BUG #3 FIX (CRITICAL): Include file_hash in the response so the frontend can
    # pass it through the create payload. Without this, JobDescription.file_hash was
    # always NULL and the cache check at line 43 could never match Ã¢â‚¬â€ every re-upload
    # of the same JD document called the LLM, wasting tokens.
    return {
        "title": ai_data.get("title", ""),
        "role": ai_data.get("role", ""),
        "description": ai_data.get("description", ""),
        "must_have_skills": ai_data.get("must_have_skills", []),
        "good_to_have_skills": ai_data.get("good_to_have_skills", []),
        "experience_min": exp_min,
        "experience_max": exp_max,
        "location": ai_data.get("location", "Remote"),
        "employment_type": ai_data.get("employment_type", "Full-time"),
        "file_hash": file_hash,
    }


@router.post("/bulk-from-documents", status_code=201)
async def bulk_create_jds_from_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Max 20 documents per bulk JD upload")

    # BUG-10 FIX: original code appended all file bytes to `raw` before any
    # parsing started (up to 20 Ãƒâ€” 5MB = 100MB in RAM). Process each file
    # incrementally and delete bytes after text extraction to keep peak RAM low.
    _ALLOWED = JD_ALLOWED_EXTENSIONS
    read_failures: list[dict] = []
    parse_failures: list[dict] = []
    valid: list[tuple[str, dict, str, bytes]] = []

    parse_sem = asyncio.Semaphore(5)

    async def _extract_and_parse_one(fname: str, content: bytes) -> dict:
        async with parse_sem:
            text = await _file_service().extract_text_from_bytes(fname, content)
            if not text.strip():
                raise ValueError("Could not extract any text from the document")
            parsed_job = await _run_jd_parser_with_fallback(
                doc_text=text,
                auth_header=request.headers.get("authorization"),
            )
            return parsed_job, text

    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in _ALLOWED:
            read_failures.append({
                "filename": f.filename,
                "error": f"Unsupported type '{ext}' - accepted: {', '.join(sorted(_ALLOWED))}",
            })
            continue
        try:
            _buf = bytearray()
            while _chunk := await f.read(1024 * 1024):
                _buf.extend(_chunk)
                if len(_buf) > 5 * 1024 * 1024:
                    raise ValueError("File exceeds 5 MB limit.")
            content = bytes(_buf)
            del _buf
        except Exception as exc:
            logger.exception("JD bulk read failed for %s", f.filename)
            read_failures.append({"filename": f.filename, "error": "Failed to read file."})
            continue

        try:
            result, raw_text = await _extract_and_parse_one(f.filename or "document.pdf", content)
            rt = (
                f"{result.get('title', '')}\n{result.get('role', '')}\n"
                f"{result.get('description', '')}\n"
                f"Must Have: {', '.join(result.get('must_have_skills') or [])}\n"
                f"Good To Have: {', '.join(result.get('good_to_have_skills') or [])}"
            )
            valid.append((f.filename or "document.pdf", result, rt, content))
            del content  # release bytes immediately after extraction
        except Exception as exc:
            logger.exception("JD bulk parse failed for %s", f.filename)
            read_failures.append({"filename": f.filename, "error": "Failed to parse document."})

    embed_sem = asyncio.Semaphore(5)

    async def _embed(raw_text: str) -> list:
        async with embed_sem:
            return await _run_jd_embedding_with_fallback(
                raw_text,
                request.headers.get("authorization"),
            )

    embed_results = await asyncio.gather(
        *[_embed(rt) for _, _, rt, _ in valid],
        return_exceptions=True,
    ) if valid else []

    success_records: list[dict] = []
    posted_jobs_for_notification: list[JobDescription] = []

    for (fname, ai_data, raw_text, content), embedding in zip(valid, embed_results):
        if isinstance(embedding, Exception):
            read_failures.append({"filename": fname, "error": f"Embedding failed: {embedding}"})
            continue

        title = (ai_data.get("title") or "").strip() or os.path.splitext(fname)[0]
        role = (ai_data.get("role") or "").strip() or title

        exp_min, exp_max = _normalize_experience_bounds(
            ai_data.get("experience_min"),
            ai_data.get("experience_max"),
        )

        jd = JobDescription(
            title=title,
            role=role,
            description=ai_data.get("description") or "",
            must_have_skills=ai_data.get("must_have_skills") or [],
            good_to_have_skills=ai_data.get("good_to_have_skills") or [],
            experience_min=exp_min,
            experience_max=exp_max,
            location=ai_data.get("location") or "Remote",
            employment_type=ai_data.get("employment_type") or "Full-time",
            salary_range=None,
            resume_weight=50,
            quiz_weight=50,
            pass_threshold=60,
            file_hash=hashlib.sha256(content).hexdigest(),
            raw_text=raw_text,
            embedding=embedding,
            created_by=user.id,
        )
        db.add(jd)
        await db.flush()
        await log_action(db, user.id, "CREATE_JD", "job_description", jd.id)
        posted_jobs_for_notification.append(jd)
        success_records.append({
            "filename": fname,
            "job_id": jd.id,
            "title": jd.title,
            "role": jd.role,
            "location": jd.location,
        })

    await db.commit()
    if posted_jobs_for_notification and not settings.DATABASE_URL.startswith("sqlite"):
        if len(posted_jobs_for_notification) == 1:
            only = posted_jobs_for_notification[0]
            background_tasks.add_task(
                _fanout_job_posted_notification_async,
                title=f"New Job Posted: {only.title}",
                message=f"{only.role} - {only.location or 'Remote'} - {only.experience_min}-{only.experience_max} yrs exp.",
                related_id=only.id,
            )
        else:
            preview = ", ".join(jd.title for jd in posted_jobs_for_notification[:3])
            more = len(posted_jobs_for_notification) - 3
            suffix = f" and {more} more" if more > 0 else ""
            background_tasks.add_task(
                _fanout_job_posted_notification_async,
                title=f"{len(posted_jobs_for_notification)} New Jobs Posted",
                message=f"{preview}{suffix}. Open Candidate Portal to view and apply.",
                related_id=posted_jobs_for_notification[0].id,
            )
    return {
        "success": success_records,
        "failed": read_failures,
        "success_count": len(success_records),
        "failed_count": len(read_failures),
    }


@router.post("/bulk-from-documents-async", status_code=202)
async def bulk_create_jds_from_documents_async(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Max 20 documents per bulk JD upload")

    allowed = JD_ALLOWED_EXTENSIONS
    files_payload: list[dict[str, Any]] = []
    read_failures: list[dict[str, Any]] = []
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in allowed:
            read_failures.append(
                {
                    "filename": f.filename,
                    "error": f"Unsupported type '{ext}' - accepted: {', '.join(sorted(allowed))}",
                }
            )
            continue

        try:
            buf = bytearray()
            while chunk := await f.read(1024 * 1024):
                buf.extend(chunk)
                if len(buf) > 5 * 1024 * 1024:
                    raise ValueError("File exceeds 5 MB limit.")
            files_payload.append({"filename": f.filename or "document.pdf", "content": bytes(buf)})
        except Exception:
            logger.exception("JD bulk async read failed for %s", f.filename)
            read_failures.append({"filename": f.filename, "error": "Failed to read file."})

    if not files_payload:
        raise HTTPException(
            status_code=422,
            detail={"message": "No valid files queued for processing", "failed": read_failures},
        )

    run_id = str(uuid4())
    db.add(
        BulkUploadJob(
            id=run_id,
            status="queued",
            created_by=user.id,
            total=len(files_payload),
            processed=0,
            failed=len(read_failures),
            details={
                "run_type": "jd_bulk_documents",
                "queued_at": _utc_now_iso(),
                "failed_precheck": read_failures,
                "status_url": f"/jd/bulk-from-documents-runs/{run_id}",
            },
        )
    )
    await db.commit()

    background_tasks.add_task(
        _run_jd_bulk_from_documents_job,
        run_id=run_id,
        files_payload=files_payload,
        auth_header=request.headers.get("authorization"),
        requested_by=user.id,
    )

    return {
        "run_id": run_id,
        "status": "queued",
        "queued_count": len(files_payload),
        "failed_precheck_count": len(read_failures),
        "poll_url": f"/jd/bulk-from-documents-runs/{run_id}",
    }


@router.get("/bulk-from-documents-runs/{run_id}")
async def bulk_create_jds_from_documents_run_status(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    run = await db.get(BulkUploadJob, run_id)
    if not run or (run.details or {}).get("run_type") != "jd_bulk_documents":
        raise HTTPException(status_code=404, detail="Run not found")
    if user.role != UserRole.admin and run.created_by and run.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not permitted to access this run")
    return {
        "run_id": run.id,
        "status": run.status,
        "total": run.total,
        "processed": run.processed,
        "failed": run.failed,
        "error_summary": run.error_summary,
        "details": run.details or {},
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


@router.post("/", response_model=JDOut, status_code=201)
@limiter.limit("20/minute")
async def create_jd(
    request: Request,
    background_tasks: BackgroundTasks,
    body: JDCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    raw_text = (
        f"{body.title}\n{body.role}\n{body.description or ''}\n"
        f"Must Have: {', '.join(body.must_have_skills)}\n"
        f"Good To Have: {', '.join(body.good_to_have_skills)}"
    )

    jd = JobDescription(
        **body.model_dump(exclude={"file_hash"}),
        raw_text=raw_text,
        file_hash=_resolve_jd_file_hash(raw_text, body.file_hash),
        created_by=user.id,
    )
    db.add(jd)
    await db.flush()
    await log_action(db, user.id, "CREATE_JD", "job_description", jd.id)
    await db.commit()
    await db.refresh(jd)
    if not settings.DATABASE_URL.startswith("sqlite"):
        background_tasks.add_task(
            _generate_and_store_jd_embedding,
            jd.id,
            raw_text,
            request.headers.get("authorization"),
        )
        logger.info("JD created jd_id=%s; embedding generation queued in background", jd.id)
    else:
        logger.info(
            "JD created jd_id=%s; deferred embedding generation skipped on sqlite to avoid lock contention",
            jd.id,
        )
    if not settings.DATABASE_URL.startswith("sqlite"):
        background_tasks.add_task(
            _fanout_job_posted_notification_async,
            title=f"New Job Posted: {jd.title}",
            message=f"{jd.role} - {jd.location or 'Remote'} - {jd.experience_min}-{jd.experience_max} yrs exp. Open now and apply before it closes.",
            related_id=jd.id,
        )
    return jd


@router.post("/generate")
async def generate_jd(
    request: Request,
    body: JDGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    gemini_service = _gemini_service()
    cache_service = _cache_service()
    exp_min, exp_max = _normalize_experience_bounds(body.experience_min, body.experience_max)
    cache_query = (
        f"Role: {body.role} Exp: {exp_min}-{exp_max} "
        f"Loc: {body.location} Ctx: {body.additional_context}"
    )
    req_embedding: list = []
    if not bool(settings.AI_FAIL_FAST_ON_UNAVAILABLE and not gemini_service.is_realtime_ai_available()):
        try:
            req_embedding = await asyncio.wait_for(
                _run_jd_embedding_with_fallback(
                    cache_query,
                    request.headers.get("authorization"),
                ),
                timeout=6.0,
            )
        except Exception as exc:
            # Cache lookup is an optimization only. If embedding is degraded, still
            # generate JD through the normal fallback chain instead of failing hard.
            logger.warning("JD generate: embedding for cache lookup failed, bypassing cache: %s", exc)

    ai_data = cache_service.get_cached_jd(req_embedding) if req_embedding else None

    if not isinstance(ai_data, dict) or not ai_data:
        ai_data = await _run_jd_generation_with_fallback(
            role=body.role,
            experience_min=exp_min,
            experience_max=exp_max,
            location=body.location,
            additional_context=body.additional_context,
            auth_header=request.headers.get("authorization"),
        )
        if isinstance(ai_data, dict) and req_embedding:
            cache_service.cache_jd(req_embedding, ai_data)

    normalized = _normalize_generated_jd(
        ai_data=ai_data if isinstance(ai_data, dict) else None,
        role=body.role,
        experience_min=exp_min,
        experience_max=exp_max,
        location=body.location,
        additional_context=body.additional_context,
    )
    schedule_adk_shadow_observation(
        workflow="jd_generation",
        inputs={
            "role": body.role,
            "experience_min": exp_min,
            "experience_max": exp_max,
            "location": body.location,
            "additional_context": body.additional_context,
        },
        production_output=normalized,
        actor_id=str(user.id),
        metadata={"route": "/jd/generate", "role": body.role},
    )
    return normalized


@router.get("/", response_model=List[JDOut])
async def list_jds(
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    # PERF: avoid loading heavy JD blob columns (`raw_text`, `embedding`) for list views.
    query = select(JobDescription).options(
        load_only(
            JobDescription.id,
            JobDescription.title,
            JobDescription.role,
            JobDescription.location,
            JobDescription.employment_type,
            JobDescription.experience_min,
            JobDescription.experience_max,
            JobDescription.must_have_skills,
            JobDescription.good_to_have_skills,
            JobDescription.description,
            JobDescription.salary_range,
            JobDescription.education_requirement,
            JobDescription.resume_weight,
            JobDescription.quiz_weight,
            JobDescription.pass_threshold,
            JobDescription.is_active,
            JobDescription.created_at,
            JobDescription.created_by,
        )
    )
    if user.role != UserRole.admin:
        query = query.where(JobDescription.created_by == user.id)
    if active_only:
        query = query.where(JobDescription.is_active == True)
    result = await db.execute(
        query.offset(skip).limit(limit).order_by(JobDescription.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{jd_id}", response_model=JDOut)
async def get_jd(
    jd_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    if user.role != UserRole.admin and jd.created_by != user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this job posting")
    return jd


@router.put("/{jd_id}", response_model=JDOut)
async def update_jd(
    jd_id: str,
    body: JDCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    gemini_service = _gemini_service()
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    if user.role != UserRole.admin and jd.created_by != user.id:
        raise HTTPException(
            status_code=403, detail="You do not have permission to edit this job posting")
    # BUG-I FIX: exclude file_hash Ã¢â‚¬â€ it's recomputed below from raw_text
    for field, value in body.model_dump(exclude={"file_hash"}).items():
        setattr(jd, field, value)
    raw_text = (
        f"{body.title}\n{body.role}\n{body.description or ''}\n"
        f"Must Have: {', '.join(body.must_have_skills)}\n"
        f"Good To Have: {', '.join(body.good_to_have_skills)}"
    )
    jd.raw_text = raw_text
    previous_embedding = jd.embedding
    should_attempt_embedding = (
        not settings.DATABASE_URL.startswith("sqlite") or _JD_UPDATE_EMBED_FORCE_ON_SQLITE
    )
    if not should_attempt_embedding:
        # Keep sqlite update path responsive under degraded AI connectivity.
        # Embedding refresh is non-critical for local runtime correctness.
        jd.embedding = previous_embedding or []
    else:
        try:
            # Keep JD edit latency bounded: embedding refresh is best-effort only.
            # For updates we call the direct embedder with a strict route-level timeout
            # and avoid harness/trace retries on the hot request path.
            emb = await asyncio.wait_for(
                gemini_service.get_embedding(raw_text),
                timeout=_JD_UPDATE_EMBED_TIMEOUT_S,
            )
            jd.embedding = emb if isinstance(emb, list) else (previous_embedding or [])
        except asyncio.TimeoutError:
            logger.warning(
                "Embedding update timed out for jd_id=%s; keeping previous embedding",
                jd_id,
            )
            jd.embedding = previous_embedding or []
        except Exception as e:
            logger.error(f"Embedding failed during JD update: {e}")
            jd.embedding = previous_embedding or []
    jd.file_hash = hashlib.sha256(raw_text.encode()).hexdigest()
    await db.flush()
    await log_action(db, user.id, "UPDATE_JD", "job_description", jd_id)
    await db.commit()
    await db.refresh(jd)
    return jd


@router.delete("/{jd_id}", response_model=MessageResponse)
async def delete_jd(
    jd_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    if user.role != UserRole.admin and jd.created_by != user.id:
        raise HTTPException(
            status_code=403, detail="You do not have permission to delete this job posting")
    # BUG-16 FIX: Distinguish delete from close.
    # close_jd only sets is_active=False (reversible soft-close).
    # delete_jd marks the JD as permanently removed by also appending [DELETED]
    # to the title to prevent accidental re-use and make it visible in admin views.
    jd.is_active = False
    if not jd.title.endswith(" [DELETED]"):
        # Ã°Å¸â€Â´ FIX: Truncate to 240 chars before appending the 10-char suffix.
        # Without this, a title already at the 255-char DB limit causes a
        # DataError (string data right truncation) Ã¢â€ â€™ 500 crash Ã¢â€ â€™ impossible
        # to delete that job.
        jd.title = f"{jd.title[:240]} [DELETED]"
    await db.flush()
    await log_action(db, user.id, "DELETE_JD", "job_description", jd_id)
    await db.commit()
    return {"message": "JD permanently deleted (soft)"}


@router.patch("/{jd_id}/close", response_model=MessageResponse)
async def close_jd(
    jd_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    if user.role != UserRole.admin and jd.created_by != user.id:
        raise HTTPException(
            status_code=403, detail="You do not have permission to close this job posting")
    jd.is_active = False
    await db.flush()
    await log_action(db, user.id, "CLOSE_JD", "job_description", jd_id)
    await db.commit()
    return {"message": "Job closed successfully"}



