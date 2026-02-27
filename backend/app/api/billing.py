"""Billing routes — Stripe checkout + portal. Uses sync DB session."""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
import stripe

from app.models.database import SyncSessionLocal, Membership, Organization, Plan
from app.services.auth_service import current_user
from app.models.database import User

router = APIRouter(prefix="/billing", tags=["billing"])


def _get_sync_db():
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _require_org_admin(db: Session, org_id: str, user_id: str):
    m = db.query(Membership).filter(
        Membership.org_id == org_id,
        Membership.user_id == user_id,
        Membership.status == "active",
    ).first()
    if not m or m.role != "org_admin":
        raise HTTPException(403, "Only org_admin allowed")
    return m


@router.post("/checkout-session")
def create_checkout_session(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(_get_sync_db),
):
    org_id = payload.get("org_id")
    plan_name = payload.get("plan_name")
    success_url = payload.get("success_url")
    cancel_url = payload.get("cancel_url")

    if not all([org_id, plan_name, success_url, cancel_url]):
        raise HTTPException(400, "Missing required fields")

    _require_org_admin(db, org_id, user.id)

    org = db.query(Organization).filter(Organization.id == org_id).first()
    plan = db.query(Plan).filter(Plan.name == plan_name).first()
    if not org or not plan:
        raise HTTPException(404, "Org or plan not found")
    if not plan.stripe_price_id:
        raise HTTPException(400, "Plan missing stripe_price_id")

    if not org.stripe_customer_id:
        cust = stripe.Customer.create(
            email=user.email,
            name=org.name,
            metadata={"org_id": str(org.id)},
        )
        org.stripe_customer_id = cust["id"]
        db.commit()

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=org.stripe_customer_id,
        line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        client_reference_id=str(org.id),
        metadata={"org_id": str(org.id), "plan": plan.name},
    )
    return {"url": session["url"], "id": session["id"]}


@router.post("/portal-session")
def create_billing_portal(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(_get_sync_db),
):
    org_id = payload.get("org_id")
    return_url = payload.get("return_url")
    if not org_id or not return_url:
        raise HTTPException(400, "Missing required fields")

    _require_org_admin(db, org_id, user.id)

    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org or not org.stripe_customer_id:
        raise HTTPException(400, "Stripe customer not set up")

    ps = stripe.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=return_url,
    )
    return {"url": ps["url"], "id": ps["id"]}


@router.get("/invoices/{org_id}")
def list_invoices(
    org_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(_get_sync_db),
):
    m = db.query(Membership).filter(
        Membership.org_id == org_id,
        Membership.user_id == user.id,
    ).first()
    if not m:
        raise HTTPException(403, "Not a member")

    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org or not org.stripe_customer_id:
        return {"invoices": []}

    inv = stripe.Invoice.list(customer=org.stripe_customer_id, limit=20)
    return {
        "invoices": [
            {
                "id": it["id"],
                "status": it.get("status"),
                "amount_due": it.get("amount_due"),
                "amount_paid": it.get("amount_paid"),
                "currency": it.get("currency"),
                "hosted_invoice_url": it.get("hosted_invoice_url"),
                "invoice_pdf": it.get("invoice_pdf"),
                "created": it.get("created"),
            }
            for it in inv.get("data", [])
        ]
    }
