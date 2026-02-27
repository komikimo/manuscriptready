"""Stripe Webhook — signature-verified, idempotent event processing."""
import logging
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import stripe

from app.core.config import settings
from app.models.database import SyncSessionLocal, Organization, StripeEvent, Invoice

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Stripe Webhook"])


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint.
    - Verifies signature using STRIPE_WEBHOOK_SECRET
    - Idempotent: skips already-processed events (unique stripe_event_id)
    - Handles: checkout.session.completed, customer.subscription.updated/deleted,
      invoice.paid/payment_failed
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    if not sig:
        raise HTTPException(400, "Missing stripe-signature header")
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET not configured")
        raise HTTPException(500, "Webhook not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(400, "Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")

    # Idempotency: skip already-processed events
    db: Session = SyncSessionLocal()
    try:
        # Record event
        try:
            db.add(StripeEvent(
                stripe_event_id=event["id"],
                event_type=event["type"],
                payload=dict(event),
            ))
            db.commit()
        except IntegrityError:
            db.rollback()
            # Already processed — skip
            return {"status": "already_processed"}

        # Dispatch
        etype = event["type"]
        data = event["data"]["object"]

        if etype == "checkout.session.completed":
            _handle_checkout_completed(db, data)
        elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
            _handle_subscription_change(db, data, etype)
        elif etype in ("invoice.paid", "invoice.payment_failed"):
            _handle_invoice(db, data, etype)
        else:
            logger.info(f"Unhandled Stripe event: {etype}")

        return {"status": "ok"}
    except Exception:
        db.rollback()
        logger.exception(f"Webhook error for event {event.get('id', '?')}")
        raise HTTPException(500, "Webhook processing error")
    finally:
        db.close()


def _handle_checkout_completed(db: Session, data: dict):
    """Checkout completed → activate subscription, update org plan."""
    org_id = data.get("client_reference_id") or (data.get("metadata") or {}).get("org_id")
    plan_name = (data.get("metadata") or {}).get("plan")
    stripe_sub_id = data.get("subscription")
    stripe_customer_id = data.get("customer")

    if not org_id:
        logger.warning("checkout.session.completed missing org_id")
        return

    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        logger.warning(f"Org {org_id} not found for checkout")
        return

    if plan_name:
        org.plan_id = plan_name
    if stripe_customer_id:
        org.stripe_customer_id = stripe_customer_id
    db.commit()
    logger.info(f"Checkout completed: org={org_id}, plan={plan_name}")


def _handle_subscription_change(db: Session, data: dict, etype: str):
    """Subscription updated or deleted → sync org plan."""
    stripe_customer_id = data.get("customer")
    if not stripe_customer_id:
        return

    org = db.query(Organization).filter(Organization.stripe_customer_id == stripe_customer_id).first()
    if not org:
        logger.warning(f"No org found for Stripe customer {stripe_customer_id}")
        return

    status = data.get("status")  # active, past_due, canceled, unpaid
    if etype == "customer.subscription.deleted" or status in ("canceled", "unpaid"):
        org.plan_id = "free"
        logger.info(f"Subscription canceled/unpaid for org {org.id}, downgraded to free")
    elif status == "active":
        # Plan might have changed — look up price → plan mapping
        items = data.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id")
            if price_id:
                from app.models.database import Plan
                plan = db.query(Plan).filter(Plan.stripe_price_id == price_id).first()
                if plan:
                    org.plan_id = plan.name
                    logger.info(f"Subscription updated for org {org.id}: plan={plan.name}")

    db.commit()


def _handle_invoice(db: Session, data: dict, etype: str):
    """Invoice paid or failed → record for accounting."""
    stripe_invoice_id = data.get("id")
    stripe_customer_id = data.get("customer")

    org = db.query(Organization).filter(Organization.stripe_customer_id == stripe_customer_id).first()
    org_id = str(org.id) if org else None

    try:
        db.merge(Invoice(
            stripe_invoice_id=stripe_invoice_id,
            org_id=org_id or "",
            status=data.get("status"),
            amount_due=data.get("amount_due"),
            amount_paid=data.get("amount_paid"),
            currency=data.get("currency"),
            hosted_invoice_url=data.get("hosted_invoice_url"),
            invoice_pdf=data.get("invoice_pdf"),
            billing_reason=data.get("billing_reason"),
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        # Update existing
        existing = db.query(Invoice).filter(Invoice.stripe_invoice_id == stripe_invoice_id).first()
        if existing:
            existing.status = data.get("status")
            existing.amount_paid = data.get("amount_paid")
            db.commit()
