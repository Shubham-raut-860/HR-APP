import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.kyc_database import KycBase


def gen_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateDocumentType(str, enum.Enum):
    aadhaar = "aadhaar"
    pan = "pan"
    employment_proof = "employment_proof"
    passport = "passport"
    driving_license = "driving_license"
    salary_slip = "salary_slip"
    offer_letter = "offer_letter"


class CandidateDocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    verified = "verified"
    rejected = "rejected"


class CandidateKycDocument(KycBase):
    __tablename__ = "candidate_kyc_documents"
    __table_args__ = (
        Index("ix_candidate_kyc_user_doc_type", "user_id", "doc_type", unique=True),
        Index("ix_candidate_kyc_user_uploaded_at", "user_id", "uploaded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    doc_type: Mapped[CandidateDocumentType] = mapped_column(SAEnum(CandidateDocumentType), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_size_kb: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[CandidateDocumentStatus] = mapped_column(
        SAEnum(CandidateDocumentStatus), default=CandidateDocumentStatus.uploaded, nullable=False
    )
    review_note: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CandidateKycConsent(KycBase):
    __tablename__ = "candidate_kyc_consents"
    __table_args__ = (
        Index(
            "ix_candidate_kyc_consent_scope",
            "candidate_id",
            "candidate_user_id",
            "recruiter_user_id",
            "job_id",
            unique=True,
        ),
        Index("ix_candidate_kyc_consent_candidate", "candidate_id"),
        Index("ix_candidate_kyc_consent_recruiter", "recruiter_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recruiter_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CandidateHireApproval(KycBase):
    __tablename__ = "candidate_hire_approvals"
    __table_args__ = (
        Index(
            "ix_candidate_hire_approval_scope",
            "candidate_id",
            "candidate_user_id",
            "recruiter_user_id",
            "job_id",
            unique=True,
        ),
        Index("ix_candidate_hire_approval_candidate", "candidate_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recruiter_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CandidateKycInvite(KycBase):
    __tablename__ = "candidate_kyc_invites"
    __table_args__ = (
        Index("ix_candidate_kyc_invite_candidate", "candidate_id"),
        Index("ix_candidate_kyc_invite_user", "candidate_user_id"),
        Index("ix_candidate_kyc_invite_job", "job_id"),
        Index("ix_candidate_kyc_invite_token_hash", "token_hash", unique=True),
        Index("ix_candidate_kyc_invite_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    candidate_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recruiter_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(512), nullable=False)
    access_scope: Mapped[str] = mapped_column(String(512), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    require_masked_aadhaar: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    legal_hold_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CandidateKycRetentionSchedule(KycBase):
    __tablename__ = "candidate_kyc_retention_schedules"
    __table_args__ = (
        Index("ix_candidate_kyc_retention_doc_id", "document_id", unique=True),
        Index("ix_candidate_kyc_retention_delete_after", "delete_after"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    delete_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
