"""
Settings router – per-user runtime configuration (SMTP credentials, etc.)

SMTP passwords are stored encrypted at rest using the existing Fernet
encryption_service so they are never visible in the database.

Endpoints
---------
GET  /settings/smtp-credentials          Return current SMTP config (password masked)
PUT  /settings/smtp-credentials          Save / update SMTP config
POST /settings/smtp-credentials/test     Send a test email to verify config
DELETE /settings/smtp-credentials        Clear saved SMTP config
"""
import logging
import smtplib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import User
from app.services.auth_service import require_hr
from app.services.encryption_service import encrypt_text, decrypt_text, DecryptionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])

# ─── Preference key used inside user.preferences JSON blob ────────────────────
_SMTP_PREF_KEY = "smtp_credentials"


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class SmtpCredentialsIn(BaseModel):
    smtp_server:   str
    smtp_port:     int
    smtp_username: str
    smtp_password: str   # plain-text on input; encrypted before storage


class SmtpCredentialsOut(BaseModel):
    smtp_server:        str
    smtp_port:          int
    smtp_username:      str
    smtp_password_hint: str  # last 4 chars of the saved password, rest masked
    configured:         bool = True


class TestEmailRequest(BaseModel):
    test_recipient: Optional[str] = None  # defaults to the HR user's own email


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_smtp(user: User) -> Optional[dict]:
    """Return the decrypted SMTP blob from user.preferences, or None."""
    prefs = user.preferences or {}
    raw = prefs.get(_SMTP_PREF_KEY)
    if not raw:
        return None
    try:
        server = raw.get("smtp_server", "smtp.gmail.com")
        port = int(raw.get("smtp_port", 587))
        username = raw.get("smtp_username", "")
        enc_pwd = raw.get("smtp_password_enc", "")
        password = decrypt_text(enc_pwd) if enc_pwd else ""
        return {"smtp_server": server, "smtp_port": port,
                "smtp_username": username, "smtp_password": password}
    except (DecryptionError, Exception) as exc:
        logger.warning("Could not decrypt SMTP credentials for user %s: %s", user.id, exc)
        return None


def _mask_password(password: str) -> str:
    if not password:
        return "••••••••"
    if len(password) <= 4:
        return "••••"
    return "••••••" + password[-4:]


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/smtp-credentials", response_model=SmtpCredentialsOut)
async def get_smtp_credentials(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """Return current SMTP config. Password is masked for display.

    If no credentials are configured yet, return a non-error empty-state payload
    so the frontend can render the form without triggering a 404 noise entry.
    """
    # Re-fetch inside this session so preferences are never stale/detached.
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    smtp = _load_smtp(db_user)
    if not smtp:
        return SmtpCredentialsOut(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            smtp_username="",
            smtp_password_hint="",
            configured=False,
        )
    return SmtpCredentialsOut(
        smtp_server=smtp["smtp_server"],
        smtp_port=smtp["smtp_port"],
        smtp_username=smtp["smtp_username"],
        smtp_password_hint=_mask_password(smtp["smtp_password"]),
    )


@router.put("/smtp-credentials", response_model=SmtpCredentialsOut)
async def save_smtp_credentials(
    body: SmtpCredentialsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """Persist SMTP credentials. Password is encrypted before storage."""
    # Re-fetch user inside this session to avoid cross-session mutation bug.
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    prefs = dict(db_user.preferences or {})
    prefs[_SMTP_PREF_KEY] = {
        "smtp_server":      body.smtp_server,
        "smtp_port":        body.smtp_port,
        "smtp_username":    body.smtp_username,
        "smtp_password_enc": encrypt_text(body.smtp_password),
    }
    db_user.preferences = prefs
    flag_modified(db_user, "preferences")
    await db.commit()

    return SmtpCredentialsOut(
        smtp_server=body.smtp_server,
        smtp_port=body.smtp_port,
        smtp_username=body.smtp_username,
        smtp_password_hint=_mask_password(body.smtp_password),
    )


@router.delete("/smtp-credentials")
async def delete_smtp_credentials(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """Remove saved SMTP credentials from user preferences."""
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    prefs = dict(db_user.preferences or {})
    prefs.pop(_SMTP_PREF_KEY, None)
    db_user.preferences = prefs
    flag_modified(db_user, "preferences")
    await db.commit()
    return {"message": "SMTP credentials cleared."}


@router.post("/smtp-credentials/test")
async def test_smtp_credentials(
    body: TestEmailRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
):
    """
    Send a test email to verify the saved SMTP configuration.
    Re-fetches the user from db so preferences and email are never stale.
    Falls back to global .env settings if no per-user SMTP is configured.
    """
    # Re-fetch so user.preferences and user.email are current in this session.
    db_user = await db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    smtp = _load_smtp(db_user)

    smtp_server = smtp["smtp_server"] if smtp else None
    smtp_port = smtp["smtp_port"] if smtp else None
    smtp_username = smtp["smtp_username"] if smtp else None
    smtp_password = smtp["smtp_password"] if smtp else None

    recipient = body.test_recipient
    if not recipient:
        raise HTTPException(
            status_code=400,
            detail="Test recipient email is required. Please type an email address."
        )

    # Inline send — bypass the background-task path so we can return the result
    # synchronously and surface SMTP errors immediately to the frontend.
    from app.config import settings as app_settings

    server = smtp_server or getattr(app_settings, "SMTP_SERVER", "")
    port = int(smtp_port or getattr(app_settings, "SMTP_PORT", 587))
    username = smtp_username or getattr(app_settings, "SMTP_USERNAME", "")
    password = smtp_password or getattr(app_settings, "SMTP_PASSWORD", "")

    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail="No SMTP credentials configured. Save your credentials first.",
        )

    subject = "HireAi – SMTP Connection Test"
    html_body = (
        "<div style='font-family:sans-serif;max-width:480px;margin:auto'>"
        "<h2 style='color:#6366f1'>✅ SMTP Test Successful</h2>"
        "<p>Your SMTP credentials are working correctly. "
        "Emails from HireAi will be delivered using this configuration.</p>"
        f"<p style='color:#888;font-size:12px'>Sent to: {recipient}<br>"
        "</div>"
    )

    def _send_test_email():
        if port == 465:
            conn = smtplib.SMTP_SSL(server, port, timeout=10)
        else:
            conn = smtplib.SMTP(server, port, timeout=10)
            conn.starttls()
            
        with conn:
            conn.login(username, password)
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            msg = MIMEMultipart()
            msg["From"] = f"HireAi <{username}>"
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html"))
            conn.send_message(msg)

    try:
        import asyncio
        await asyncio.to_thread(_send_test_email)
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(
            status_code=400,
            detail="Authentication failed. Check your username and password (or App Password for Gmail).",
        )
    except smtplib.SMTPConnectError:
        raise HTTPException(
            status_code=400,
            # FIX Finding 11: redact server/port from error response
            detail="Could not connect to the SMTP server. Check the server address and port in Settings.",
        )
    except Exception as exc:
        logger.error("SMTP test failed for user %s: %s", user.id if hasattr(user, 'id') else 'unknown', exc)
        raise HTTPException(status_code=400, detail="SMTP test failed. Check your configuration and try again.")

    return {"message": f"Test email sent successfully to {recipient}."}
