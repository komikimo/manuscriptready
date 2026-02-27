from sqlalchemy.orm import Session
from typing import List, Optional
from ..models.database import OrgSetting

def get_or_create_org_settings(db: Session, org_id) -> OrgSetting:
    s = db.query(OrgSetting).filter(OrgSetting.org_id == org_id).first()
    if not s:
        s = OrgSetting(org_id=org_id, admins_can_access_content=False, domain_allowlist=[], auto_join_enabled=False)
        db.add(s); db.commit(); db.refresh(s)
    return s

def domain_is_allowed(allowlist: List[str], domain: str) -> bool:
    domain = (domain or "").lower().strip(".")
    for d in (allowlist or []):
        dd = (d or "").lower().strip(".")
        if domain == dd or domain.endswith("." + dd):
            return True
    return False
