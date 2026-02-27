from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import hashlib

from ..db.session import get_db
from ..models.database import SCIMToken, Membership, User

router = APIRouter(prefix="/scim/v2", tags=["scim"])

def _auth_scim(req: Request, db: Session) -> str:
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing SCIM token")
    token = auth.split(" ", 1)[1].strip()
    h = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = db.query(SCIMToken).filter(SCIMToken.token_hash == h, SCIMToken.is_enabled == True).first()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid SCIM token")
    return str(row.org_id)

@router.get("/Users")
def list_users(req: Request, db: Session = Depends(get_db)):
    org_id = _auth_scim(req, db)
    members = db.query(Membership).filter(Membership.org_id == org_id).all()
    users = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        if not u:
            continue
        users.append({
            "id": str(u.id),
            "userName": u.email,
            "active": True,
            "name": {"formatted": u.email},
        })
    return {"Resources": users, "totalResults": len(users), "itemsPerPage": len(users), "startIndex": 1,
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]}

@router.post("/Users")
def create_user(req: Request, payload: dict, db: Session = Depends(get_db)):
    org_id = _auth_scim(req, db)
    email = (payload.get("userName") or (payload.get("emails") or [{}])[0].get("value") or "").lower()
    if not email:
        raise HTTPException(status_code=400, detail="Missing userName/email")
    u = db.query(User).filter(User.email == email).first()
    if not u:
        raise HTTPException(status_code=400, detail="User must sign up first (scaffold)")
    exists = db.query(Membership).filter(Membership.org_id == org_id, Membership.user_id == u.id).first()
    if not exists:
        db.add(Membership(org_id=org_id, user_id=u.id, role="researcher", status="active"))
        db.commit()
    return {"id": str(u.id), "userName": u.email, "active": True, "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"]}

@router.delete("/Users/{user_id}")
def delete_user(req: Request, user_id: str, db: Session = Depends(get_db)):
    org_id = _auth_scim(req, db)
    m = db.query(Membership).filter(Membership.org_id == org_id, Membership.user_id == user_id).first()
    if m:
        db.delete(m); db.commit()
    return {}
