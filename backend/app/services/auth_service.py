"""
Auth Service — JWT + bcrypt
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.database import User, Subscription

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_pw(p): return pwd.hash(p)
def verify_pw(plain, hashed): return pwd.verify(plain, hashed)

def create_token(uid: str) -> str:
    return jwt.encode({"sub": uid, "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES)},
                      settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def decode_token(token: str) -> Optional[str]:
    try: return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]).get("sub")
    except: return None

async def create_user(db: AsyncSession, email, password, name="", inst="") -> User:
    exists = await db.execute(select(User).where(User.email == email.lower()))
    if exists.scalar_one_or_none(): raise ValueError("Email already registered")
    u = User(email=email.lower(), hashed_password=hash_pw(password), full_name=name, institution=inst)
    db.add(u); await db.flush()
    db.add(Subscription(user_id=u.id, tier="free", status="active"))
    await db.commit(); await db.refresh(u); return u

async def auth_user(db: AsyncSession, email, password) -> Optional[User]:
    r = await db.execute(select(User).where(User.email == email.lower()))
    u = r.scalar_one_or_none()
    if not u or not verify_pw(password, u.hashed_password): return None
    return u

async def get_user(db: AsyncSession, uid: str) -> Optional[User]:
    r = await db.execute(select(User).where(User.id == uid))
    return r.scalar_one_or_none()

async def get_sub(db: AsyncSession, uid: str) -> Optional[Subscription]:
    r = await db.execute(select(Subscription).where(Subscription.user_id == uid))
    return r.scalar_one_or_none()
