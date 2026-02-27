"""Database Models — Production-safe with constraints"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, JSON, Date, Numeric, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, func
import uuid
from app.core.config import settings


class Base(DeclarativeBase):
    pass


def genuuid():
    return str(uuid.uuid4())


# ═══════════════════════════════════════════
#  CORE USER / SUBSCRIPTION
# ═══════════════════════════════════════════

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=genuuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), default="")
    institution = Column(String(255), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    documents = relationship("Document", back_populates="user", order_by="Document.created_at.desc()")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(String, primary_key=True, default=genuuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    tier = Column(String(20), default="free")
    status = Column(String(20), default="active")
    stripe_customer_id = Column(String(255), default="")
    stripe_subscription_id = Column(String(255), default="")
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    words_used = Column(Integer, default=0)
    user = relationship("User", back_populates="subscription")

    @property
    def words_limit(self):
        return {"free": settings.QUOTA_FREE, "starter": settings.QUOTA_STARTER,
                "pro": settings.QUOTA_PRO, "team": settings.QUOTA_TEAM}.get(self.tier, 1000)

    @property
    def words_remaining(self):
        return max(0, self.words_limit - self.words_used)

    @property
    def can_process(self):
        return self.status in ("active", "trialing") and self.words_remaining > 0


# ═══════════════════════════════════════════
#  MULTI-TENANT ORG MODEL
# ═══════════════════════════════════════════

class Organization(Base):
    __tablename__ = "organizations"
    id = Column(String, primary_key=True, default=genuuid)
    name = Column(String(255), nullable=False)
    plan_id = Column(String(64), default="free")
    stripe_customer_id = Column(String(128), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Membership(Base):
    __tablename__ = "memberships"
    id = Column(String, primary_key=True, default=genuuid)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), default="researcher")  # org_admin | lab_admin | researcher
    status = Column(String(32), default="active")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
    )


# ═══════════════════════════════════════════
#  DOCUMENTS & VERSIONS
# ═══════════════════════════════════════════

class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=genuuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), default="Untitled")
    section_type = Column(String(50), default="general")
    original_text = Column(Text, default="")
    text = Column(Text, default="")  # canonical server-side text for processing
    improved_text = Column(Text, default="")
    revised_text = Column(Text, default="")
    mode = Column(String(50), default="enhance")
    status = Column(String(32), default="draft")  # draft | processing | revised | failed
    word_count = Column(Integer, default=0)
    score_before = Column(JSON, default=dict)
    score_after = Column(JSON, default=dict)
    reviewer_alerts = Column(JSON, default=list)
    diffs = Column(JSON, default=list)
    processing_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="documents")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id = Column(String, primary_key=True, default=genuuid)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version_number = Column(Integer, nullable=False)
    source = Column(String(32), default="manual")
    content_type = Column(String(16), default="text")
    s3_key_original = Column(String(1024), default="")
    s3_key_processed = Column(String(1024), default="")
    checksum_sha256 = Column(String(64), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_docver_doc_num"),
    )


# ═══════════════════════════════════════════
#  PROCESSING JOBS
# ═══════════════════════════════════════════

class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id = Column(String, primary_key=True, default=genuuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(String(32), default="academic")
    status = Column(String(16), default="queued")  # queued | running | succeeded | failed | canceled
    progress = Column(Integer, default=0)
    stage = Column(String(32), default="queued")
    error_message = Column(Text, default="")
    word_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


# Partial unique index: only one active job per document
# Enforced at DB level to prevent double-enqueue
ACTIVE_JOB_INDEX = Index(
    "uq_active_job_per_doc",
    ProcessingJob.document_id,
    unique=True,
    postgresql_where=(ProcessingJob.status.in_(["queued", "running"])),
)


# ═══════════════════════════════════════════
#  USAGE METERING
# ═══════════════════════════════════════════

class UsageLedgerDaily(Base):
    __tablename__ = "usage_ledger_daily"
    id = Column(String, primary_key=True, default=genuuid)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    date = Column(Date, nullable=False)
    words_rewrite = Column(Integer, default=0)
    words_translate = Column(Integer, default=0)
    docs_processed = Column(Integer, default=0)
    tokens_prompt = Column(Integer, default=0)
    tokens_completion = Column(Integer, default=0)
    cost_usd_est = Column(Float, default=0.0)
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", "date", name="uq_usage_daily_org_user_date"),
    )


# ═══════════════════════════════════════════
#  AUDIT & EVENTS
# ═══════════════════════════════════════════

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(String, primary_key=True, default=genuuid)
    org_id = Column(String, default="")
    user_id = Column(String, default="")
    action = Column(String(128), nullable=False)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(128), default="")
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════
#  PLANS & ORG POLICIES
# ═══════════════════════════════════════════

class Plan(Base):
    __tablename__ = "plans"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), nullable=False, unique=True)
    stripe_price_id = Column(String(128), nullable=True)
    limits_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrgSetting(Base):
    __tablename__ = "org_settings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
    admins_can_access_content = Column(Boolean, nullable=False, default=False)
    domain_allowlist = Column(JSONB, nullable=False, default=list)
    auto_join_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class DocAdminGrant(Base):
    __tablename__ = "doc_admin_grants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    granted_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("document_id", "org_id", name="uq_doc_admin_grant"),)


# ═══════════════════════════════════════════
#  STRIPE EVENTS / INVOICES
# ═══════════════════════════════════════════

class StripeEvent(Base):
    __tablename__ = "stripe_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stripe_event_id = Column(String(128), nullable=False, unique=True)
    event_type = Column(String(128), nullable=False)
    org_id = Column(String, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    stripe_invoice_id = Column(String(128), nullable=False, unique=True)
    status = Column(String(64), nullable=True)
    amount_due = Column(Numeric(12, 2), nullable=True)
    amount_paid = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(8), nullable=True)
    hosted_invoice_url = Column(String(512), nullable=True)
    invoice_pdf = Column(String(512), nullable=True)
    billing_reason = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ═══════════════════════════════════════════
#  SSO / SCIM (enterprise scaffold)
# ═══════════════════════════════════════════

class SSOConnection(Base):
    __tablename__ = "sso_connections"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
    provider = Column(String(32), nullable=False)
    oidc_config = Column(JSONB, nullable=True)
    saml_config = Column(JSONB, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False)
    subject = Column(String(256), nullable=False)
    email = Column(String(256), nullable=True)
    org_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_external_identity"),)


class SCIMToken(Base):
    __tablename__ = "scim_tokens"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
    token_hash = Column(String(256), nullable=False)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ═══════════════════════════════════════════
#  ENGINE / SESSION FACTORIES
# ═══════════════════════════════════════════

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for Celery workers (separate connection pool)
_sync_url = settings.DATABASE_URL.replace("+asyncpg", "").replace("+aiosqlite", "")
sync_engine = create_engine(_sync_url, echo=False, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
