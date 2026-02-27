"""Celery tasks — production-safe, sync-only, no document text in Redis."""
import logging
from datetime import datetime, timezone, date
from celery import shared_task
from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from app.models.database import (
    SyncSessionLocal, Document, ProcessingJob, UsageLedgerDaily,
    Plan, Organization, DocumentVersion,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════

def _word_count(txt: str) -> int:
    return len(txt.split()) if txt else 0


def _bump_usage_idempotent(
    db: Session,
    org_id: str,
    user_id: str,
    words_rewrite: int = 0,
    words_translate: int = 0,
    docs_processed: int = 0,
    tokens_prompt: int = 0,
    tokens_completion: int = 0,
    cost_usd_est: float = 0.0,
):
    """
    Idempotent usage ledger upsert using INSERT ... ON CONFLICT UPDATE.
    Prevents duplicate rows under concurrency. Uses DB-level uniqueness
    on (org_id, user_id, date).
    """
    today = date.today()
    db.execute(sql_text("""
        INSERT INTO usage_ledger_daily (id, org_id, user_id, date,
            words_rewrite, words_translate, docs_processed,
            tokens_prompt, tokens_completion, cost_usd_est)
        VALUES (gen_random_uuid(), :org_id, :user_id, :today,
            :wr, :wt, :docs, :tp, :tc, :cost)
        ON CONFLICT (org_id, user_id, date) DO UPDATE SET
            words_rewrite = usage_ledger_daily.words_rewrite + :wr,
            words_translate = usage_ledger_daily.words_translate + :wt,
            docs_processed = usage_ledger_daily.docs_processed + :docs,
            tokens_prompt = usage_ledger_daily.tokens_prompt + :tp,
            tokens_completion = usage_ledger_daily.tokens_completion + :tc,
            cost_usd_est = usage_ledger_daily.cost_usd_est + :cost
    """), {
        "org_id": org_id, "user_id": user_id, "today": today,
        "wr": words_rewrite, "wt": words_translate, "docs": docs_processed,
        "tp": tokens_prompt, "tc": tokens_completion, "cost": cost_usd_est,
    })
    db.commit()


# ═══════════════════════════════════════════
#  MAIN PROCESSING TASK
# ═══════════════════════════════════════════

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    name="processing.run_job",
)
def run_processing_job(self, job_id: str):
    """
    Main document processing task.
    - Reads document text from DB (never from Redis/task args)
    - Runs rewrite pipeline
    - Bumps usage ONLY on success
    - Marks job failed on error (no usage bump)
    """
    db: Session = SyncSessionLocal()
    try:
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return {"status": "missing"}

        # Guard: skip if already running/succeeded (idempotency)
        if job.status in ("succeeded", "running"):
            return {"status": job.status, "message": "already processed"}

        job.status = "running"
        job.progress = 5
        job.stage = "loading"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        doc = db.query(Document).filter(Document.id == job.document_id).first()
        if not doc:
            job.status = "failed"
            job.error_message = "Document not found"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "failed"}

        # Verify org isolation: job.org_id must match doc.org_id
        if str(job.org_id) != str(doc.org_id):
            job.status = "failed"
            job.error_message = "Org mismatch"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "failed"}

        input_text = doc.text or doc.original_text or ""
        if not input_text.strip():
            job.status = "failed"
            job.error_message = "No text to process"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "failed"}

        wc = _word_count(input_text)

        # ── REWRITE ──
        job.stage = "rewrite"
        job.progress = 10
        db.commit()

        # Import here to avoid circular imports at worker startup
        import asyncio
        from app.services.rewrite_engine import get_rewriter

        rewriter = get_rewriter()
        loop = asyncio.new_event_loop()
        try:
            revised = loop.run_until_complete(
                rewriter.rewrite(input_text, mode=job.mode or "academic")
            )
        finally:
            loop.close()

        job.progress = 55
        job.stage = "review"
        db.commit()

        # ── REVIEW + SCORE ──
        from app.services.reviewer_engine import analyze_text
        from app.services.scoring_engine import compute_score
        from app.services.diff_service import compute_diffs

        alerts = analyze_text(revised)
        score = compute_score(input_text, revised)
        diffs = compute_diffs(input_text, revised)

        # ── SAVE RESULTS ──
        doc.revised_text = revised
        doc.improved_text = revised
        doc.reviewer_alerts = alerts
        doc.score_after = score
        doc.diffs = diffs
        doc.status = "revised"

        job.progress = 100
        job.stage = "done"
        job.status = "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

        # ── BUMP USAGE (only on success) ──
        mode = job.mode or "academic"
        _bump_usage_idempotent(
            db,
            org_id=str(doc.org_id),
            user_id=str(job.user_id),
            words_rewrite=wc if mode != "translate" else 0,
            words_translate=wc if mode == "translate" else 0,
            docs_processed=1,
        )

        return {"status": "ok", "job_id": job_id}

    except Exception as exc:
        db.rollback()
        # Mark job as failed — NO usage bump
        try:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job and job.status != "succeeded":
                job.status = "failed"
                job.stage = "failed"
                job.error_message = str(exc)[:1000]
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            logger.exception(f"Failed to mark job {job_id} as failed")
        raise  # Re-raise for Celery retry
    finally:
        db.close()


# ═══════════════════════════════════════════
#  SCHEDULED: RETENTION PURGE
# ═══════════════════════════════════════════

from app.worker.celery_app import celery_app

@celery_app.task(name="retention.purge_expired_documents")
def purge_expired_documents():
    """Purge expired docs based on plan retention_days. Batch SQL delete."""
    from datetime import timedelta
    db: Session = SyncSessionLocal()
    try:
        orgs = db.query(Organization).all()
        for org in orgs:
            plan_key = org.plan_id or "free"
            plan = db.query(Plan).filter(Plan.name == plan_key).first()
            if not plan:
                plan = db.query(Plan).filter(Plan.name == "free").first()
            retention_days = int((plan.limits_json or {}).get("retention_days", 30)) if plan else 30
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            # Batch delete: DocumentVersion cascade handled by ON DELETE CASCADE
            expired_ids = [
                d.id for d in
                db.query(Document.id)
                .filter(Document.org_id == org.id, Document.updated_at < cutoff)
                .limit(500)
                .all()
            ]
            if expired_ids:
                db.query(Document).filter(Document.id.in_(expired_ids)).delete(synchronize_session=False)
                db.commit()

        return {"ok": True}
    except Exception:
        db.rollback()
        logger.exception("Purge failed")
        return {"ok": False}
    finally:
        db.close()
