"""
Auth router  register, login, me, forgot-password, reset-password
"""
import html
import logging
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Body
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import User, UserRole, RefreshToken, UsedResetToken
from app.schemas import UserCreate, UserOut, UserUpdate, LoginRequest, Token
from app.services.auth_service import (
    hash_password, verify_password,
    create_access_token, get_current_user,
    issue_refresh_token, rotate_refresh_token,
    revoke_refresh_token, revoke_access_jti, decode_token,
    log_action,
    bearer_scheme,
    DUMMY_PASSWORD_HASH,
)
from app.services.email_service import send_email_async
from app.config import settings
from app.limiter import limiter, _get_real_ip
from app.utils.password_policy import validate_password

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)
_optional_bearer = HTTPBearer(auto_error=False)

# ─── Schemas ──────────────────────────────────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class VerifyResetTokenRequest(BaseModel):
    token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None

def _validate_new_password_or_400(password: str) -> str:
    try:
        return validate_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _verify_password_or_false(plain: str, hashed: str) -> bool:
    try:
        return verify_password(plain, hashed)
    except ValueError:
        return False


def _is_valid_hr_invite(submitted_code: str | None) -> bool:
    expected_codes = settings.hr_invite_codes_list
    provided = (submitted_code or "").strip()
    if not expected_codes or not provided:
        return False
    return any(secrets.compare_digest(provided, expected) for expected in expected_codes)


async def _verify_reset_token_or_400(token: str, db: AsyncSession) -> tuple[User, str, datetime]:
    """Validate reset token integrity and one-time-use constraints."""
    try:
        unverified_payload = jwt.get_unverified_claims(token)
        email = unverified_payload.get("sub")
        if not email or not isinstance(email, str):
            raise ValueError("missing sub")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    dynamic_secret = f"{settings.SECRET_KEY}{user.hashed_password}"
    try:
        payload = jwt.decode(token, dynamic_secret, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "reset":
            raise ValueError("invalid token type")
        jti = payload.get("jti")
        if not isinstance(jti, str) or not jti.strip():
            raise ValueError("missing jti")
    except (JWTError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    exp_claim = payload.get("exp")
    if not isinstance(exp_claim, (int, float)):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    expires_at = datetime.fromtimestamp(float(exp_claim), tz=timezone.utc)
    if datetime.now(timezone.utc) >= expires_at:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    existing_used = (
        await db.execute(select(UsedResetToken).where(UsedResetToken.jti == jti))
    ).scalar_one_or_none()
    if existing_used:
        raise HTTPException(status_code=400, detail="Token already used")

    return user, jti, expires_at

# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit("30/minute")
async def register(request: Request, body: UserCreate, db: AsyncSession = Depends(get_db)):
    email = body.email.lower()
    requested_role = UserRole(body.role)

    if requested_role == UserRole.hr and settings.hr_registration_requires_invite:
        if not _is_valid_hr_invite(body.hr_invite_code):
            raise HTTPException(
                status_code=403,
                detail="A valid recruiter invite code is required to register as HR.",
            )

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=requested_role,
        is_active=True,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # TOCTOU FIX: two concurrent requests passed the SELECT check simultaneously.
        # The DB unique constraint fires on commit — catch it and return a clean 409.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    body.email = body.email.lower()
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    
    # Timing Attack Mitigation
    if not user:
        _verify_password_or_false(body.password, DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    if not _verify_password_or_false(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(
            status_code=403, detail="Account has been disabled. Contact your administrator.")

    token = create_access_token({"sub": user.id, "role": user.role})
    refresh_token = await issue_refresh_token(db, user.id)

    # FIX (Bug #2 - HIGH): Previously used request.client.host which always logs the
    # reverse-proxy IP, not the real client IP. Use _get_real_ip() to honour
    # X-Forwarded-For / X-Real-IP headers exactly as the rate limiter does.
    real_ip = _get_real_ip(request)
    await log_action(db, user.id, "LOGIN", "auth", ip_address=real_ip)
    await db.commit()
    return Token(access_token=token, refresh_token=refresh_token, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=Token)
@limiter.limit("20/minute")
async def refresh_access_token(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    user_id, new_refresh_token = await rotate_refresh_token(db, body.refresh_token.strip())
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    new_access = create_access_token({"sub": user.id, "role": user.role})
    await log_action(db, user.id, "REFRESH_TOKEN", "auth", ip_address=_get_real_ip(request))
    await db.commit()
    return Token(access_token=new_access, refresh_token=new_refresh_token, user=UserOut.model_validate(user))


@router.post("/logout")
@limiter.limit("20/minute")
async def logout(
    request: Request,
    body: LogoutRequest = Body(default=LogoutRequest()),
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: AsyncSession = Depends(get_db),
):
    actor_user_id: str | None = None

    # Best-effort access token revocation. Access token is optional for logout
    # so users can still invalidate refresh tokens after access expiry.
    if credentials and credentials.credentials:
        try:
            payload = decode_token(credentials.credentials)
            jti = payload.get("jti")
            exp = payload.get("exp")
            token_sub = payload.get("sub")
            if token_sub and isinstance(token_sub, str):
                actor_user_id = token_sub
            if jti and exp:
                exp_dt = datetime.fromtimestamp(float(exp), tz=timezone.utc)
                await revoke_access_jti(
                    db,
                    jti=str(jti),
                    expires_at=exp_dt,
                    user_id=actor_user_id,
                )
        except Exception as exc:
            logger.warning("Logout access-token revoke skipped: %s", exc)

    # Always revoke refresh token when provided, even if access token is absent/expired.
    if body.refresh_token:
        refresh_user_id = await revoke_refresh_token(db, body.refresh_token.strip())
        if refresh_user_id and not actor_user_id:
            actor_user_id = refresh_user_id

    if actor_user_id:
        await log_action(db, actor_user_id, "LOGOUT", "auth", ip_address=_get_real_ip(request))
    await db.commit()
    return {"message": "Logged out successfully"}


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    body.email = body.email.lower()
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user:
        dynamic_secret = f"{settings.SECRET_KEY}{user.hashed_password}"
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
        to_encode = {
            "sub": user.email,
            "exp": expire,
            "type": "reset",
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(to_encode, dynamic_secret, algorithm=settings.ALGORITHM)

        base_url = settings.FRONTEND_URL.rstrip("/")
        reset_link = f"{base_url}/reset-password/{token}"
        safe_link = html.escape(reset_link, quote=True)
        subject = "Secure Password Reset Request"
        html_body = f"<p>You requested a password reset. Click the link below to set a new password. This link securely expires in 15 minutes.</p><p><a href='{safe_link}'>Reset Password</a></p>"
        # BUG #1 FIX (CRITICAL): Use background_tasks instead of awaiting inline.
        # Previously, SMTP failures raised HTTP 503 for real users but the dummy-hash
        # path always returned 200 — trivially enumerable. Sending in the background
        # ensures both paths always return 200 with identical timing.
        background_tasks.add_task(send_email_async, user.email, subject, html_body)
    else:
        # No dummy hash here. With SMTP running in background_tasks, both paths are incredibly fast. 
        # Adding a dummy hash here creates an inverse timing differential.
        pass

    return {"message": "If that email exists in our system, a password reset link has been sent."}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    _validate_new_password_or_400(body.new_password)
    user, jti, expires_at = await _verify_reset_token_or_400(body.token, db)

    db.add(
        UsedResetToken(
            user_id=user.id,
            jti=jti,
            used_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Token already used")

    user.hashed_password = hash_password(body.new_password)
    user.token_revoked_before = datetime.now(timezone.utc)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"message": "Password updated successfully"}


@router.post("/reset-password/verify")
@limiter.limit("20/minute")
async def verify_reset_password_token(
    request: Request,
    body: VerifyResetTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    await _verify_reset_token_or_400(body.token, db)
    return {"valid": True, "message": "Reset token is valid"}


@router.get("/me", response_model=UserOut)
@limiter.limit("120/minute")
async def me(request: Request, current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserOut)
@limiter.limit("10/minute")
async def update_me(request: Request, body: UserUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # BUG 11 FIX: get_current_user uses its own session; mutating that object and
    # committing a *different* db session is an async SQLAlchemy anti-pattern —
    # changes may silently not persist or raise DetachedInstanceError under load.
    # Re-fetch the user within this request's session before mutating.
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.full_name is not None:
        db_user.full_name = body.full_name
    if body.bio is not None:
        db_user.bio = body.bio
    if body.preferences is not None:
        db_user.preferences = body.preferences

    await log_action(db, user.id, "UPDATE_PROFILE", "auth")
    await db.commit()
    await db.refresh(db_user)
    return db_user


@router.post("/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Change the authenticated user's password by verifying the current one."""
    # BUG #17 FIX (MEDIUM): Re-fetch user within this request's session FIRST,
    # then verify against the fresh db_user.hashed_password — not the stale
    # `user` object from get_current_user's separate session.
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not _verify_password_or_false(body.current_password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    # Policy enforced in app.utils.password_policy.validate_password().
    _validate_new_password_or_400(body.new_password)
    if _verify_password_or_false(body.new_password, db_user.hashed_password):
        raise HTTPException(
            status_code=400, detail="New password must be different from the current password")

    db_user.hashed_password = hash_password(body.new_password)
    db_user.token_revoked_before = datetime.now(timezone.utc)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == db_user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await log_action(db, user.id, "CHANGE_PASSWORD", "auth")
    await db.commit()  # commit password change + audit log in one transaction
    return {"message": "Password changed successfully"}
