"""
Authentication service – JWT creation, password hashing, role guards
"""
import uuid
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.config import settings
from app.database import get_db
from app.models import User, UserRole, AuditLog, RefreshToken, RevokedToken
from app.utils.password_policy import MAX_BYTES


bearer_scheme = HTTPBearer()
_BCRYPT_MODULE = None


def _bcrypt():
    global _BCRYPT_MODULE
    if _BCRYPT_MODULE is None:
        import bcrypt as _bcrypt_module
        _BCRYPT_MODULE = _bcrypt_module
    return _BCRYPT_MODULE


_BCRYPT_ROUNDS = int(getattr(settings, "BCRYPT_ROUNDS", 12))
# Keep a static bcrypt hash to avoid expensive gensalt/hash work at import-time.
# This hash is non-secret and only used for constant-time credential checks when
# a user does not exist.
_DUMMY_HASH = "$2b$12$kq22MyZhK2sAwTa67D48ce9zxYLCKp1sOT128RN1h.YBIorYuwpgC"
DUMMY_PASSWORD_HASH = _DUMMY_HASH


def _assert_bcrypt_safe(password: str) -> None:
    if len(password.encode("utf-8")) > MAX_BYTES:
        raise ValueError(
            f"Password exceeds bcrypt maximum input length ({MAX_BYTES} bytes)"
        )


def hash_password(password: str) -> str:
    _assert_bcrypt_safe(password)
    bcrypt = _bcrypt()
    # Rounds are configurable via settings.BCRYPT_ROUNDS (default 12).
    # Increase as hardware improves — each +1 doubles hashing time.
    # FOLLOW-UP: add BCRYPT_ROUNDS: int = 12 to app/config.py Settings class.
    rounds: int = int(getattr(settings, "BCRYPT_ROUNDS", 12))
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    _assert_bcrypt_safe(plain)
    bcrypt = _bcrypt()
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    to_encode["iat"] = now              # issued-at: enables "invalidate all tokens before X"
    to_encode["jti"] = str(uuid.uuid4())  # unique ID: enables per-token revocation via blocklist
    to_encode["type"] = "access"
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def issue_refresh_token(db: AsyncSession, user_id: str) -> str:
    raw = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash_refresh_token(raw),
            expires_at=expires,
            created_at=now,
        )
    )
    await db.flush()
    return raw


async def rotate_refresh_token(db: AsyncSession, raw_refresh_token: str) -> tuple[str, str]:
    token_hash = _hash_refresh_token(raw_refresh_token)
    now = datetime.now(timezone.utc)
    new_raw = secrets.token_urlsafe(48)
    new_hash = _hash_refresh_token(new_raw)
    revoked_result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(
            revoked_at=now,
            replaced_by_token_hash=new_hash,
        )
        .returning(RefreshToken.user_id)
    )
    revoked_row = revoked_result.first()
    if not revoked_row:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = str(revoked_row[0])
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=new_hash,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            created_at=now,
        )
    )
    await db.flush()
    return user_id, new_raw


async def revoke_refresh_token(db: AsyncSession, raw_refresh_token: str) -> str | None:
    token_hash = _hash_refresh_token(raw_refresh_token)
    now = datetime.now(timezone.utc)
    row = (await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )).scalar_one_or_none()
    if not row:
        return None
    if row.revoked_at is None:
        row.revoked_at = now
        await db.flush()
    return str(row.user_id) if row.user_id else None


async def revoke_access_jti(
    db: AsyncSession,
    jti: str,
    expires_at: datetime,
    user_id: str | None = None,
) -> None:
    existing = (await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))).scalar_one_or_none()
    if existing:
        return
    db.add(
        RevokedToken(
            user_id=user_id,
            jti=jti,
            expires_at=expires_at,
            revoked_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti.strip():
        raise HTTPException(status_code=401, detail="Invalid token payload")
    revoked = (await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))).scalar_one_or_none()
    if revoked:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    issued_at = payload.get("iat")
    if user.token_revoked_before and issued_at:
        try:
            if isinstance(issued_at, (int, float)):
                issued_at_dt = datetime.fromtimestamp(float(issued_at), tz=timezone.utc)
            elif isinstance(issued_at, str):
                # jose may emit ISO-like strings in some integrations
                issued_at_dt = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
            else:
                issued_at_dt = None
        except Exception:
            issued_at_dt = None
        if issued_at_dt is not None:
            revoked_before = user.token_revoked_before
            if revoked_before.tzinfo is None:
                revoked_before = revoked_before.replace(tzinfo=timezone.utc)
            if issued_at_dt <= revoked_before:
                raise HTTPException(status_code=401, detail="Token is no longer valid")
    return user


async def require_hr(user: User = Depends(get_current_user)) -> User:
    """Allow hr and admin roles — blocks candidates from HR endpoints."""
    if user.role not in (UserRole.hr, UserRole.admin):
        raise HTTPException(status_code=403, detail="HR or Admin access required")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_candidate(user: User = Depends(get_current_user)) -> User:
    """Only candidate role — blocks HR from candidate-only endpoints."""
    if user.role != UserRole.candidate:
        raise HTTPException(status_code=403, detail="Candidate access required")
    return user


async def log_action(
    db: AsyncSession,
    user_id: Optional[str],
    action: str,
    resource: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
):
    # Safeguard database parameters from Postgres string overflow exceptions
    safe_action = (action[:97] + "...") if action and len(action) > 100 else action
    safe_resource = (resource[:97] + "...") if resource and len(resource) > 100 else resource
    safe_rid = resource_id[:36] if resource_id else None
    safe_ip = ip_address[:50] if ip_address else None

    log = AuditLog(
        user_id=user_id,
        action=safe_action,
        resource=safe_resource,
        resource_id=safe_rid,
        details=details,
        ip_address=safe_ip,
    )
    db.add(log)
    # flush() stages the row in the current transaction without committing.
    # The caller owns the commit — this keeps audit logs atomic with the main
    # operation and avoids expiring ORM objects mid-request (SQLAlchemy expires
    # all objects on commit, which breaks any subsequent attribute access).
    await db.flush()
