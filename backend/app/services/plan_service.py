from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from ..models.database import Plan, Organization

def get_org_plan(session: Session, org_id) -> Optional[Plan]:
    org = session.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        return None
    plan_key = getattr(org, "plan_id", None) or "free"
    # plan_id may be stored as name for simplicity in this scaffold
    plan = session.query(Plan).filter(Plan.name == str(plan_key)).first()
    if plan:
        return plan
    return session.query(Plan).filter(Plan.name == "free").first()

def get_limits(plan: Plan) -> Dict[str, Any]:
    return plan.limits_json or {}
