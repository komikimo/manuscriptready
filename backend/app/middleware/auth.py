"""Auth Middleware"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import User, Subscription, get_db
from app.services.auth_service import decode_token, get_user, get_sub

security = HTTPBearer()

async def current_user(cred: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)) -> User:
    uid = decode_token(cred.credentials)
    if not uid: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    u = await get_user(db, uid)
    if not u or not u.is_active: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return u

async def require_sub(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    sub = await get_sub(db, user.id)
    if not sub or not sub.can_process:
        detail = "Quota exhausted — upgrade your plan" if sub and sub.words_remaining <= 0 else "Active subscription required"
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail)
    return user, sub
