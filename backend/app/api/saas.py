"""SaaS routes — production-safe, tenant-isolated, quota-enforced"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from sqlalchemy import select, func, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    get_db, User, Organization, Membership, Document, DocumentVersion,
    ProcessingJob, Plan, UsageLedgerDaily, Subscription, OrgSetting, DocAdminGrant,
)
from app.services.auth_service import current_user
from app.services.storage_service import put_bytes, presign_get
from app.services.docx_service import extract_docx, extract_latex
from app.worker.tasks import run_processing_job

router = APIRouter(prefix="/saas", tags=["SaaS"])


# ═══════════════════════════════════════════
#  INTERNAL HELPERS
# ═══════════════════════════════════════════

def _wc(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


async def _get_billing_period(db: AsyncSession, org_id: str):
    """Get billing period: Stripe subscription period or calendar month fallback."""
    r = await db.execute(
        select(Subscription).where(Subscription.org_id == org_id)
    )
    sub = r.scalar_one_or_none()
    if sub and sub.current_period_start and sub.current_period_end:
        return sub.current_period_start.date(), sub.current_period_end.date()
    # Calendar month fallback
    now = datetime.now(timezone.utc)
    start = date(now.year, now.month, 1)
    if now.month == 12:
        end = date(now.year, 12, 31)
    else:
        end = date(now.year, now.month + 1, 1).fromordinal(
            date(now.year, now.month + 1, 1).toordinal() - 1
        )
    return start, end


async def _enforce_quota_precheck(
    db: AsyncSession, org_id: str, plan_name: str, word_count: int, mode: str
):
    """Pre-enqueue quota enforcement. Raises 402/413 on violation."""
    r = await db.execute(select(Plan).where(Plan.name == plan_name))
    plan = r.scalar_one_or_none()
    limits = (plan.limits_json if plan else {}) or {}
    words_month = int(limits.get("words_month", 10_000_000))
    docs_month = int(limits.get("docs_month", 10_000))
    max_doc_words = int(limits.get("max_doc_words", 200_000))

    if word_count > max_doc_words:
        raise HTTPException(413, {"message": "Document too large for plan", "max_doc_words": max_doc_words})

    start, end = await _get_billing_period(db, org_id)
    agg = await db.execute(
        select(
            func.coalesce(func.sum(UsageLedgerDaily.words_rewrite), 0),
            func.coalesce(func.sum(UsageLedgerDaily.words_translate), 0),
            func.coalesce(func.sum(UsageLedgerDaily.docs_processed), 0),
        ).where(and_(
            UsageLedgerDaily.org_id == org_id,
            UsageLedgerDaily.date >= start,
            UsageLedgerDaily.date <= end,
        ))
    )
    wr, wt, docs = agg.one()

    add_wr = word_count if mode != "translate" else 0
    add_wt = word_count if mode == "translate" else 0
    projected_words = int(wr) + int(wt) + add_wr + add_wt
    projected_docs = int(docs) + 1

    reasons = []
    if projected_words > words_month:
        reasons.append("words_month_exceeded")
    if projected_docs > docs_month:
        reasons.append("docs_month_exceeded")

    if reasons:
        raise HTTPException(402, {
            "message": "Plan limits exceeded",
            "plan": plan_name,
            "limits": {"words_month": words_month, "docs_month": docs_month},
            "usage": {"words_total": int(wr) + int(wt), "docs_processed": int(docs)},
            "projected": {"words_total": projected_words, "docs_processed": projected_docs},
            "reasons": reasons,
        })


async def _get_org_for_user(db: AsyncSession, u: User) -> Organization:
    """Get user's org (highest-role first). Auto-create personal workspace if none."""
    r = await db.execute(
        select(Organization)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == u.id, Membership.status == "active")
        .order_by(Membership.role.desc())
    )
    org = r.scalars().first()
    if org:
        return org

    # Auto-create personal workspace
    org = Organization(
        name=(u.full_name or u.email.split("@")[0]) + " Workspace",
        plan_id="free",
    )
    db.add(org)
    await db.flush()
    db.add(Membership(org_id=org.id, user_id=u.id, role="org_admin", status="active"))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Concurrent creation — re-query
        r = await db.execute(
            select(Organization)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == u.id)
        )
        org = r.scalars().first()
    await db.refresh(org)
    return org


async def _require_org_member(db: AsyncSession, org_id: str, user_id: str, roles: list[str] | None = None) -> Membership:
    """Verify user is a member of org. Optionally require specific roles."""
    r = await db.execute(
        select(Membership).where(
            Membership.org_id == org_id,
            Membership.user_id == user_id,
            Membership.status == "active",
        )
    )
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(403, "Not a member of this organization")
    if roles and m.role not in roles:
        raise HTTPException(403, f"Requires role: {', '.join(roles)}")
    return m


async def _verify_doc_ownership(db: AsyncSession, doc_id: str, org_id: str) -> Document:
    """Load document and verify it belongs to org."""
    d = await db.get(Document, doc_id)
    if not d or str(d.org_id) != str(org_id):
        raise HTTPException(404, "Document not found")
    return d


# ═══════════════════════════════════════════
#  USER / ORG INFO
# ═══════════════════════════════════════════

@router.get("/me")
async def me(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    org = await _get_org_for_user(db, u)
    return {
        "user": {"id": u.id, "email": u.email, "name": u.full_name},
        "org": {"id": org.id, "name": org.name, "plan": org.plan_id},
    }


# ═══════════════════════════════════════════
#  DOCUMENT CRUD
# ═══════════════════════════════════════════

@router.post("/docs")
async def create_doc(payload: dict = Body(...), u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    org = await _get_org_for_user(db, u)
    title = (payload.get("title") or "Untitled").strip()[:500]
    d = Document(user_id=u.id, org_id=org.id, title=title)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return {"id": d.id, "title": d.title, "status": "draft"}


@router.get("/docs")
async def list_docs(u: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    org = await _get_org_for_user(db, u)
    r = await db.execute(
        select(Document)
        .where(Document.org_id == org.id)
        .order_by(Document.created_at.desc())
        .limit(50)
    )
    docs = r.scalars().all()
    return [
        {"id": d.id, "title": d.title, "status": d.status, "created_at": d.created_at, "updated_at": d.updated_at}
        for d in docs
    ]


# ═══════════════════════════════════════════
#  FILE UPLOAD (no quota check — upload only)
# ═══════════════════════════════════════════

@router.post("/docs/{doc_id}/upload")
async def upload_doc(
    doc_id: str,
    file: UploadFile = File(...),
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_for_user(db, u)
    d = await _verify_doc_ownership(db, doc_id, org.id)

    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 25MB)")

    name = (file.filename or "").lower()
    if name.endswith(".docx"):
        text, meta = extract_docx(data)
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif name.endswith(".tex") or name.endswith(".zip"):
        text, meta = extract_latex(data, filename=file.filename or "upload")
        content_type = "application/octet-stream"
    else:
        raise HTTPException(400, "Unsupported file type (.docx, .tex, .zip)")

    # S3 key scoped to org
    key = f"org/{org.id}/docs/{doc_id}/original/{secrets.token_hex(8)}-{file.filename or 'upload'}"
    put_bytes(key, data, content_type=content_type)

    # Next version number
    r = await db.execute(
        select(func.coalesce(func.max(DocumentVersion.version_number), 0))
        .where(DocumentVersion.document_id == doc_id)
    )
    next_v = r.scalar_one() + 1

    v = DocumentVersion(
        document_id=doc_id,
        created_by_user_id=u.id,
        version_number=next_v,
        source="upload",
        content_type="docx" if name.endswith(".docx") else "latex",
        s3_key_original=key,
        checksum_sha256=_sha256(data),
    )
    db.add(v)
    d.original_text = text
    d.text = text
    d.word_count = _wc(text)
    await db.commit()
    await db.refresh(v)
    return {"version_id": v.id, "version_number": v.version_number, "word_count": d.word_count}


# ═══════════════════════════════════════════
#  VERSIONS (read-only — no quota check)
# ═══════════════════════════════════════════

@router.get("/docs/{doc_id}/versions")
async def list_versions(
    doc_id: str,
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_for_user(db, u)
    await _verify_doc_ownership(db, doc_id, org.id)

    r = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_number.desc())
    )
    vs = r.scalars().all()
    return [
        {"id": x.id, "n": x.version_number, "source": x.source, "created_at": x.created_at}
        for x in vs
    ]


# ═══════════════════════════════════════════
#  PROCESS ENQUEUE — Quota + Double-Enqueue Guard
# ═══════════════════════════════════════════

@router.post("/process")
async def enqueue_process(
    payload: dict = Body(...),
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_org_for_user(db, u)
    doc_id = payload.get("doc_id")
    mode = payload.get("mode") or "academic"

    if not doc_id:
        raise HTTPException(400, "doc_id required")

    d = await _verify_doc_ownership(db, doc_id, org.id)

    # Derive text server-side — never trust client
    canonical_text = (d.text or d.original_text or "").strip()
    if not canonical_text:
        raise HTTPException(400, "No document text available. Upload a .docx/.tex first.")

    wc = _wc(canonical_text)

    # Quota precheck
    plan_name = org.plan_id or "free"
    await _enforce_quota_precheck(db, str(org.id), plan_name, wc, mode)

    # Create job — DB partial unique index prevents double-enqueue
    job = ProcessingJob(
        user_id=u.id,
        document_id=doc_id,
        org_id=org.id,
        mode=mode,
        status="queued",
        progress=0,
        stage="queued",
        word_count=wc,
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Document is already being processed")

    await db.refresh(job)

    # Enqueue to Celery — pass only IDs, never document text
    run_processing_job.delay(str(job.id))
    return {"job_id": job.id, "status": job.status}


# ═══════════════════════════════════════════
#  JOB STATUS
# ═══════════════════════════════════════════

@router.get("/jobs/{job_id}")
async def job_status(
    job_id: str,
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ProcessingJob, job_id)
    if not job or job.user_id != u.id:
        raise HTTPException(404, "Job not found")
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error_message,
    }


# ═══════════════════════════════════════════
#  DOWNLOAD — S3 key validated against org
# ═══════════════════════════════════════════

@router.post("/download")
async def download_url(
    payload: dict = Body(...),
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    key = payload.get("s3_key")
    if not key:
        raise HTTPException(400, "s3_key required")

    # CRITICAL: validate S3 key belongs to user's org
    org = await _get_org_for_user(db, u)
    expected_prefix = f"org/{org.id}/"
    if not key.startswith(expected_prefix):
        raise HTTPException(403, "Access denied")

    return {"url": presign_get(key)}


# ═══════════════════════════════════════════
#  ORG SETTINGS (async, proper auth)
# ═══════════════════════════════════════════

@router.get("/orgs/{org_id}/settings")
async def get_org_settings(
    org_id: str,
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(db, org_id, u.id, roles=["org_admin", "lab_admin"])
    r = await db.execute(select(OrgSetting).where(OrgSetting.org_id == org_id))
    s = r.scalar_one_or_none()
    if not s:
        s = OrgSetting(org_id=org_id)
        db.add(s)
        await db.commit()
        await db.refresh(s)

    r2 = await db.execute(select(Plan).where(Plan.name == (
        (await db.get(Organization, org_id)).plan_id or "free"
    )))
    plan = r2.scalar_one_or_none()
    return {
        "org_id": org_id,
        "admins_can_access_content": s.admins_can_access_content,
        "domain_allowlist": s.domain_allowlist,
        "auto_join_enabled": s.auto_join_enabled,
        "plan": plan.name if plan else "free",
        "limits": plan.limits_json if plan else {},
    }


@router.patch("/orgs/{org_id}/settings")
async def update_org_settings(
    org_id: str,
    payload: dict = Body(...),
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(db, org_id, u.id, roles=["org_admin"])
    r = await db.execute(select(OrgSetting).where(OrgSetting.org_id == org_id))
    s = r.scalar_one_or_none()
    if not s:
        s = OrgSetting(org_id=org_id)
        db.add(s)
        await db.flush()

    if "admins_can_access_content" in payload:
        s.admins_can_access_content = bool(payload["admins_can_access_content"])
    if "domain_allowlist" in payload:
        s.domain_allowlist = payload["domain_allowlist"] or []
    if "auto_join_enabled" in payload:
        s.auto_join_enabled = bool(payload["auto_join_enabled"])
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════
#  ORG USAGE (async, member-gated)
# ═══════════════════════════════════════════

@router.get("/orgs/{org_id}/usage")
async def get_org_usage(
    org_id: str,
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_member(db, org_id, u.id)

    start, end = await _get_billing_period(db, org_id)
    agg = await db.execute(
        select(
            func.coalesce(func.sum(UsageLedgerDaily.words_rewrite), 0),
            func.coalesce(func.sum(UsageLedgerDaily.words_translate), 0),
            func.coalesce(func.sum(UsageLedgerDaily.docs_processed), 0),
        ).where(and_(
            UsageLedgerDaily.org_id == org_id,
            UsageLedgerDaily.date >= start,
            UsageLedgerDaily.date <= end,
        ))
    )
    wr, wt, docs = agg.one()

    org = await db.get(Organization, org_id)
    r2 = await db.execute(select(Plan).where(Plan.name == (org.plan_id or "free")))
    plan = r2.scalar_one_or_none()

    return {
        "org_id": org_id,
        "plan": plan.name if plan else "free",
        "period": {"start_date": str(start), "end_date": str(end)},
        "usage": {"words_rewrite": int(wr), "words_translate": int(wt), "docs_processed": int(docs)},
        "limits": plan.limits_json if plan else {},
    }


# ═══════════════════════════════════════════
#  DOC ADMIN GRANT (async, owner-only)
# ═══════════════════════════════════════════

@router.post("/docs/{doc_id}/grant-admin-access")
async def grant_admin_access(
    doc_id: str,
    u: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    d = await db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    if str(d.user_id) != str(u.id):
        raise HTTPException(403, "Only document owner can grant admin access")

    # Check existing
    r = await db.execute(
        select(DocAdminGrant).where(
            DocAdminGrant.document_id == d.id,
            DocAdminGrant.org_id == d.org_id,
        )
    )
    if not r.scalar_one_or_none():
        db.add(DocAdminGrant(document_id=d.id, org_id=d.org_id, granted_by_user_id=u.id))
        await db.commit()
    return {"ok": True}
