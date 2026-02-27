"""Auth Service & Middleware"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.database import User, Subscription, Organization, Membership, get_db

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def hash_pw(p: str) -> str:
    return pwd.hash(p)

def verify_pw(plain: str, hashed: str) -> bool:
    return pwd.verify(plain, hashed)

def create_token(uid: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES)
    return jwt.encode({"sub": uid, "exp": exp}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def decode_token(token: str) -> Optional[str]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]).get("sub")
    except jwt.PyJWTError:
        return None

async def create_user(db: AsyncSession, email: str, password: str, name: str = "", inst: str = "") -> User:
    r = await db.execute(select(User).where(User.email == email.lower()))
    if r.scalar_one_or_none():
        raise ValueError("Email already registered")
    u = User(email=email.lower(), hashed_password=hash_pw(password), full_name=name, institution=inst)
    db.add(u)
    await db.flush()

    # Backward-compatible personal subscription
    db.add(Subscription(user_id=u.id, tier="free", status="active"))

    # SaaS: create a personal organization + membership
    org = Organization(name=(name or email.split("@")[0]) + " Workspace", plan_id="free")
    db.add(org)
    await db.flush()
    db.add(Membership(org_id=org.id, user_id=u.id, role="org_admin", status="active"))

    await db.commit()
    await db.refresh(u)
    return u

async def auth_user(db: AsyncSession, email: str, password: str) -> Optional[User]:
    r = await db.execute(select(User).where(User.email == email.lower()))
    u = r.scalar_one_or_none()
    return u if u and verify_pw(password, u.hashed_password) else None

async def get_user(db: AsyncSession, uid: str) -> Optional[User]:
    return (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()

async def get_sub(db: AsyncSession, uid: str) -> Optional[Subscription]:
    return (await db.execute(select(Subscription).where(Subscription.user_id == uid))).scalar_one_or_none()

# ── Middleware Dependencies ──
async def current_user(
    cred: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    uid = decode_token(cred.credentials)
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    u = await get_user(db, uid)
    if not u or not u.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return u

async def require_sub(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = await get_sub(db, user.id)
    if not sub or not sub.can_process:
        msg = "Quota exhausted" if sub and sub.words_remaining <= 0 else "Subscription required"
        raise HTTPException(status.HTTP_403_FORBIDDEN, msg)
    return user, sub


def auto_join_by_domain(db: Session, user):
    """Institutional auto-join:
    If user's email domain matches any org_settings.domain_allowlist where auto_join_enabled=true,
    create membership as researcher.
    """
    try:
        email = (getattr(user, "email", "") or "").lower()
        if "@" not in email:
            return
        domain = email.split("@", 1)[1].strip().lower()
        from ..models.database import OrgSetting, Membership
        settings = db.query(OrgSetting).filter(OrgSetting.auto_join_enabled == True).all()
        for s in settings:
            allow = s.domain_allowlist or []
            if any(domain == d or domain.endswith("." + d) for d in allow):
                exists = db.query(Membership).filter(Membership.org_id == s.org_id, Membership.user_id == user.id).first()
                if not exists:
                    db.add(Membership(org_id=s.org_id, user_id=user.id, role="researcher", status="active"))
                    db.commit()
                return
    except Exception:
        db.rollback()
        return
