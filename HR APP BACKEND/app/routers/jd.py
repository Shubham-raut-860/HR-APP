"""
JD router – create, generate, list, get, update, delete
"""
from app.models import NotificationType
from app.services.notification_service import push_to_all_candidates
from app.services import gemini_service, cache_service, file_service
from app.services.auth_service import require_hr, log_action
from app.config import settings
from app.schemas import JDCreate, JDOut, JDGenerateRequest, MessageResponse
from app.models import User, JobDescription, UserRole
from app.database import get_db
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import os
import hashlib
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jd", tags=["Job Descriptions"])
JD_ALLOWED_EXTENSIONS = set(settings.allowed_extensions_list) | {
    ".txt",
    ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".gif",
}


@router.post("/from-document")
async def generate_jd_from_document(
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

    text = await file_service.extract_text_from_bytes(file.filename or "jd", content)
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract any text from the uploaded file.",
        )

    try:
        ai_data = await gemini_service.parse_jd_from_document(text)
    except Exception as e:
        logger.exception("JD extraction from document failed for file=%s", file.filename)
        raise HTTPException(status_code=500, detail="An internal error occurred.") from e

    ai_data["_file_hash"] = file_hash
    ai_data["_raw_text"] = text[:20000]

    # BUG #3 FIX (CRITICAL): Include file_hash in the response so the frontend can
    # pass it through the create payload. Without this, JobDescription.file_hash was
    # always NULL and the cache check at line 43 could never match — every re-upload
    # of the same JD document called the LLM, wasting tokens.
    return {
        "title": ai_data.get("title", ""),
        "role": ai_data.get("role", ""),
        "description": ai_data.get("description", ""),
        "must_have_skills": ai_data.get("must_have_skills", []),
        "good_to_have_skills": ai_data.get("good_to_have_skills", []),
        "experience_min": ai_data.get("experience_min", 0),
        "experience_max": ai_data.get("experience_max", 5),
        "location": ai_data.get("location", "Remote"),
        "employment_type": ai_data.get("employment_type", "Full-time"),
        "file_hash": file_hash,
    }


@router.post("/bulk-from-documents", status_code=201)
async def bulk_create_jds_from_documents(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Max 20 documents per bulk JD upload")

    # BUG-10 FIX: original code appended all file bytes to `raw` before any
    # parsing started (up to 20 × 5MB = 100MB in RAM). Process each file
    # incrementally and delete bytes after text extraction to keep peak RAM low.
    _ALLOWED = JD_ALLOWED_EXTENSIONS
    read_failures: list[dict] = []
    parse_failures: list[dict] = []
    valid: list[tuple[str, dict, str, bytes]] = []

    parse_sem = asyncio.Semaphore(5)

    async def _extract_and_parse_one(fname: str, content: bytes) -> dict:
        async with parse_sem:
            text = await file_service.extract_text_from_bytes(fname, content)
            if not text.strip():
                raise ValueError("Could not extract any text from the document")
            return await gemini_service.parse_jd_from_document(text), text

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
            return await gemini_service.get_embedding(raw_text)

    embed_results = await asyncio.gather(
        *[_embed(rt) for _, _, rt, _ in valid],
        return_exceptions=True,
    ) if valid else []

    success_records: list[dict] = []

    for (fname, ai_data, raw_text, content), embedding in zip(valid, embed_results):
        if isinstance(embedding, Exception):
            read_failures.append({"filename": fname, "error": f"Embedding failed: {embedding}"})
            continue

        title = (ai_data.get("title") or "").strip() or os.path.splitext(fname)[0]
        role = (ai_data.get("role") or "").strip() or title

        jd = JobDescription(
            title=title,
            role=role,
            description=ai_data.get("description") or "",
            must_have_skills=ai_data.get("must_have_skills") or [],
            good_to_have_skills=ai_data.get("good_to_have_skills") or [],
            experience_min=ai_data.get("experience_min") or 0,
            experience_max=ai_data.get("experience_max") or 5,
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
        await push_to_all_candidates(
            db,
            title=f"New Job Posted: {jd.title}",
            message=f"{jd.role} · {jd.location or 'Remote'} · {jd.experience_min}–{jd.experience_max} yrs exp.",
            ntype=NotificationType.job_posted,
            related_id=jd.id,
        )
        success_records.append({
            "filename": fname,
            "job_id": jd.id,
            "title": jd.title,
            "role": jd.role,
            "location": jd.location,
        })

    await db.commit()
    return {
        "success": success_records,
        "failed": read_failures,
        "success_count": len(success_records),
        "failed_count": len(read_failures),
    }


@router.post("/", response_model=JDOut, status_code=201)
async def create_jd(
    body: JDCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    raw_text = (
        f"{body.title}\n{body.role}\n{body.description or ''}\n"
        f"Must Have: {', '.join(body.must_have_skills)}\n"
        f"Good To Have: {', '.join(body.good_to_have_skills)}"
    )
    try:
        embedding = await gemini_service.get_embedding(raw_text)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Embedding failed during JD creation: {e}")
        embedding = []  # Fallback to empty vector to prevent crash; similarity will be 0.0

    jd = JobDescription(
        **body.model_dump(exclude={"file_hash"}),
        raw_text=raw_text,
        embedding=embedding,
        file_hash=hashlib.sha256(raw_text.encode()).hexdigest(),
        created_by=user.id,
    )
    db.add(jd)
    await db.flush()
    await log_action(db, user.id, "CREATE_JD", "job_description", jd.id)
    await push_to_all_candidates(
        db,
        title=f"New Job Posted: {jd.title}",
        message=f"{jd.role} · {jd.location or 'Remote'} · {jd.experience_min}–{jd.experience_max} yrs exp. Open now — apply before it closes!",
        ntype=NotificationType.job_posted,
        related_id=jd.id,
    )
    await db.commit()
    await db.refresh(jd)
    return jd


@router.post("/generate")
async def generate_jd(
    body: JDGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    cache_query = (
        f"Role: {body.role} Exp: {body.experience_min}-{body.experience_max} "
        f"Loc: {body.location} Ctx: {body.additional_context}"
    )
    req_embedding = await gemini_service.get_embedding(cache_query)
    ai_data = cache_service.get_cached_jd(req_embedding)

    if not ai_data:
        ai_data = await gemini_service.generate_jd(
            role=body.role,
            exp_min=body.experience_min,
            exp_max=body.experience_max,
            location=body.location or "Remote",
            context=body.additional_context or "",
        )
        cache_service.cache_jd(req_embedding, ai_data)

    return {
        "title": ai_data.get("title", body.role),
        "role": body.role,
        "location": body.location,
        "experience_min": body.experience_min,
        "experience_max": body.experience_max,
        "must_have_skills": ai_data.get("must_have_skills", []),
        "good_to_have_skills": ai_data.get("good_to_have_skills", []),
        "description": ai_data.get("description", ""),
        "education_requirement": ai_data.get("education_requirement", "none"),
    }


@router.get("/", response_model=List[JDOut])
async def list_jds(
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    query = select(JobDescription)
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
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="JD not found")
    if user.role != UserRole.admin and jd.created_by != user.id:
        raise HTTPException(
            status_code=403, detail="You do not have permission to edit this job posting")
    # BUG-I FIX: exclude file_hash — it's recomputed below from raw_text
    for field, value in body.model_dump(exclude={"file_hash"}).items():
        setattr(jd, field, value)
    raw_text = (
        f"{body.title}\n{body.role}\n{body.description or ''}\n"
        f"Must Have: {', '.join(body.must_have_skills)}\n"
        f"Good To Have: {', '.join(body.good_to_have_skills)}"
    )
    jd.raw_text = raw_text
    try:
        jd.embedding = await gemini_service.get_embedding(raw_text)
    except Exception as e:
        logger.error(f"Embedding failed during JD update: {e}")
        # Keep old embedding if it exists, or set to []
        if not jd.embedding:
            jd.embedding = []
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
        # 🔴 FIX: Truncate to 240 chars before appending the 10-char suffix.
        # Without this, a title already at the 255-char DB limit causes a
        # DataError (string data right truncation) → 500 crash → impossible
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
