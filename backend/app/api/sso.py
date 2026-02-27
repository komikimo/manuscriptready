from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import hashlib, secrets

from ..db.session import get_db
from ..services.auth_service import get_current_user
from ..models.database import Membership, SSOConnection, SCIMToken

router = APIRouter(prefix="/enterprise", tags=["enterprise"])

def _require_org_admin(db: Session, org_id: str, user_id: str):
    m = db.query(Membership).filter(Membership.org_id == org_id, Membership.user_id == user_id).first()
    if not m or m.role != "org_admin":
        raise HTTPException(status_code=403, detail="Only org_admin allowed")
    return m

@router.get("/sso/{org_id}")
def get_sso(org_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_org_admin(db, org_id, user.id)
    c = db.query(SSOConnection).filter(SSOConnection.org_id == org_id).first()
    return {"enabled": bool(c and c.is_enabled), "provider": (c.provider if c else None),
            "oidc_config": (c.oidc_config if c else None), "saml_config": (c.saml_config if c else None)}

@router.put("/sso/{org_id}/oidc")
def upsert_oidc(org_id: str, payload: dict, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_org_admin(db, org_id, user.id)
    c = db.query(SSOConnection).filter(SSOConnection.org_id == org_id).first()
    if not c:
        c = SSOConnection(org_id=org_id, provider="oidc", oidc_config={}, saml_config=None, is_enabled=False)
        db.add(c)
    c.provider = "oidc"
    c.oidc_config = payload or {}
    if "is_enabled" in payload:
        c.is_enabled = bool(payload["is_enabled"])
    db.commit()
    return {"ok": True}

@router.post("/scim/{org_id}/token")
def create_scim_token(org_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_org_admin(db, org_id, user.id)
    raw = secrets.token_urlsafe(32)
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    t = db.query(SCIMToken).filter(SCIMToken.org_id == org_id).first()
    if not t:
        t = SCIMToken(org_id=org_id, token_hash=h, created_by_user_id=user.id, is_enabled=True)
        db.add(t)
    else:
        t.token_hash = h
        t.is_enabled = True
    db.commit()
    return {"token": raw}

@router.post("/scim/{org_id}/token/disable")
def disable_scim_token(org_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _require_org_admin(db, org_id, user.id)
    t = db.query(SCIMToken).filter(SCIMToken.org_id == org_id).first()
    if t:
        t.is_enabled = False
        db.commit()
    return {"ok": True}
