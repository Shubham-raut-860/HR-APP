"""
Email service – SMTP-based email delivery.

FIXES APPLIED:
 #7  Removed broken html_content.replace("\\n", "<br>") — content is already HTML.
 #8  Propagate failures via exception instead of silently swallowing them.
 #12 Centralise SMTP config in Settings class instead of scattered os.getenv() calls.
 #NEW Module-level constants (SMTP_SERVER / PORT / USERNAME / PASSWORD) were evaluated
     once at import time.  Any runtime credential update — e.g. via the new
     PUT /settings/smtp-credentials endpoint — was silently ignored for the lifetime of
     the process.  Replaced with a helper that reads from `settings` on every call so
     dynamic credential changes take effect immediately without a restart.
 #NEW Added optional per-call smtp_* kwargs so callers (or tests) can supply
     credentials without touching global settings.
"""
import logging
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class EmailSendError(RuntimeError):
    """Raised when email delivery fails so callers can handle it."""


def _redact_email(addr: str) -> str:
    try:
        local, domain = str(addr).rsplit("@", 1)
        return local[:2] + "***@" + domain
    except Exception:
        return "***"


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    smtp_server: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_username: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """Send an HTML email via SMTP.

    Per-call kwargs (smtp_server / smtp_port / smtp_username / smtp_password) take
    precedence over the global settings values.  This lets HR users configure their
    own outbound SMTP credentials at runtime without a server restart.
    """
    # Read fresh on every call — never use module-level cached constants.
    server = smtp_server or settings.SMTP_SERVER
    port = int(smtp_port or settings.SMTP_PORT)
    username = smtp_username or settings.SMTP_USERNAME
    password = smtp_password or settings.SMTP_PASSWORD
    redacted_to = _redact_email(to_email)

    if not username or not password:
        logger.warning(
            "Cannot send email to %s — SMTP username/password not configured.",
            redacted_to,
        )
        # FIX Finding 17: raise instead of silent return so callers know email wasn't sent
        raise EmailSendError(
            f"Cannot send email to {redacted_to} — SMTP credentials not configured. "
            "Set SMTP_USERNAME and SMTP_PASSWORD in Settings."
        )

    msg = MIMEMultipart()
    # Use SMTP_FROM_EMAIL if configured; otherwise fall back to the SMTP username.
    # FOLLOW-UP: add SMTP_FROM_EMAIL: str = "" to app/config.py Settings class.
    from_addr = getattr(settings, "SMTP_FROM_EMAIL", "") or username
    msg["From"] = f"Jobora <{from_addr}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # FIX #7: html_content is already fully-formed HTML. The old `.replace("\n", "<br>")`
    # injected <br> tags inside HTML attribute values and code blocks — stripped here.
    msg.attach(MIMEText(html_content, "html"))

    # TLS context with certificate verification — prevents MITM on the SMTP leg.
    tls_ctx = ssl.create_default_context()

    try:
        if port == 465:
            # Port 465: implicit TLS (SMTP_SSL) — connection is encrypted from the start.
            with smtplib.SMTP_SSL(server, port, timeout=30, context=tls_ctx) as conn:
                conn.login(username, password)
                conn.send_message(msg)
        else:
            # Port 587 (or other): STARTTLS upgrade with verified TLS context.
            # Timeout raised from 10s → 30s to avoid intermittent failures on
            # slower SMTP servers (corporate relays, SES in remote regions).
            with smtplib.SMTP(server, port, timeout=30) as conn:
                conn.starttls(context=tls_ctx)
                conn.login(username, password)
                conn.send_message(msg)
        logger.info("Email successfully sent to %s", redacted_to)
    except Exception as exc:
        # FIX #8: log AND re-raise so callers know delivery failed.
        logger.error("Failed to send email to %s: %s", redacted_to, exc)
        raise EmailSendError(
            f"Failed to send email to {redacted_to}: {exc}"
        ) from exc


def send_email_with_retry(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    attempts: int = 3,
    initial_delay_seconds: float = 1.0,
    smtp_server: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_username: Optional[str] = None,
    smtp_password: Optional[str] = None,
) -> None:
    """Send email with bounded retry for transient SMTP/TLS failures."""
    attempts = max(1, int(attempts))
    last_error: Exception | None = None
    smtp_kwargs = {
        key: value
        for key, value in {
            "smtp_server": smtp_server,
            "smtp_port": smtp_port,
            "smtp_username": smtp_username,
            "smtp_password": smtp_password,
        }.items()
        if value is not None
    }
    for attempt in range(1, attempts + 1):
        try:
            send_email(
                to_email,
                subject,
                html_content,
                **smtp_kwargs,
            )
            if attempt > 1:
                logger.info("Email sent to %s after %d attempt(s)", _redact_email(to_email), attempt)
            return
        except EmailSendError as exc:
            last_error = exc
            if attempt >= attempts:
                break
            delay = initial_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Email send attempt %d/%d failed for %s; retrying in %.1fs: %s",
                attempt,
                attempts,
                _redact_email(to_email),
                delay,
                exc,
            )
            time.sleep(delay)

    raise EmailSendError(
        f"Failed to send email to {_redact_email(to_email)} after {attempts} attempt(s): {last_error}"
    ) from last_error


async def get_fallback_smtp_credentials() -> Optional[dict]:
    """Fetch the admin user's SMTP credentials from the DB as a fallback.

    The SMTP blob in user.preferences is a plain dict with the password stored
    under 'smtp_password_enc' (individually encrypted by settings_router.py).
    """
    from app.database import AsyncSessionLocal
    from sqlalchemy import select
    from app.models import User, UserRole
    from app.services.encryption_service import decrypt_text

    async with AsyncSessionLocal() as session:
        # .order_by(created_at.asc()) ensures the oldest ("primary") admin is
        # always selected deterministically when multiple admins exist.
        admin = (await session.execute(
            select(User)
            .where(User.role == UserRole.admin)
            .order_by(User.created_at.asc())
        )).scalars().first()
        if not admin:
            return None

        prefs = getattr(admin, "preferences", {}) or {}
        smtp_blob = prefs.get("smtp_credentials")
        if not smtp_blob or not isinstance(smtp_blob, dict):
            return None
        try:
            enc_password = smtp_blob.get("smtp_password_enc")
            # Security hardening: ignore legacy/plaintext blobs.
            # Admin should re-save SMTP credentials so password is encrypted at rest.
            if not enc_password:
                logger.warning(
                    "Ignoring unencrypted SMTP credential blob for admin user %s; "
                    "re-save SMTP credentials to restore email sending.",
                    admin.id,
                )
                return None
            password = decrypt_text(enc_password)
            return {
                "smtp_server": smtp_blob.get("smtp_server", ""),
                "smtp_port": smtp_blob.get("smtp_port", 587),
                "smtp_username": smtp_blob.get("smtp_username", ""),
                "smtp_password": password,
            }
        except Exception:
            return None


def _resolve_smtp_password(smtp_creds: Optional[dict]) -> Optional[str]:
    if not smtp_creds:
        return None
    # Preferred: encrypted blob path.
    enc = smtp_creds.get("smtp_password_enc")
    if enc:
        try:
            from app.services.encryption_service import decrypt_text
            return decrypt_text(str(enc))
        except Exception:
            logger.warning("Failed to decrypt smtp_password_enc from smtp_creds payload.")
            return None
    # Backward compatible: explicit runtime plain value (never persisted by this module).
    return smtp_creds.get("smtp_password")


async def send_email_async(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    smtp_creds: Optional[dict] = None
) -> None:
    """Async wrapper that applies fallback credentials and runs SMTP loosely matched."""
    if not smtp_creds:
        smtp_creds = await get_fallback_smtp_credentials()

    server = smtp_creds.get("smtp_server") if smtp_creds else None
    port = smtp_creds.get("smtp_port") if smtp_creds else None
    username = smtp_creds.get("smtp_username") if smtp_creds else None
    password = _resolve_smtp_password(smtp_creds)

    import asyncio
    await asyncio.to_thread(
        send_email_with_retry,
        to_email,
        subject,
        html_content,
        smtp_server=server,
        smtp_port=port,
        smtp_username=username,
        smtp_password=password
    )
