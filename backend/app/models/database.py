"""
Database Models — SQLAlchemy Async ORM
"""
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import uuid
from app.core.config import settings


class Base(DeclarativeBase):
    pass

def genuuid():
    return str(uuid.uuid4())

def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=genuuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), default="")
    institution = Column(String(255), default="")
    created_at = Column(DateTime, default=utcnow)
    is_active = Column(Boolean, default=True)
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    documents = relationship("Document", back_populates="user", order_by="Document.created_at.desc()")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(String, primary_key=True, default=genuuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True)
    tier = Column(String(20), default="free")
    status = Column(String(20), default="active")
    stripe_customer_id = Column(String(255), default="")
    stripe_subscription_id = Column(String(255), default="")
    words_used = Column(Integer, default=0)
    quota_reset = Column(DateTime, default=utcnow)
    user = relationship("User", back_populates="subscription")

    @property
    def words_limit(self):
        return {"free": settings.QUOTA_FREE, "starter": settings.QUOTA_STARTER,
                "pro": settings.QUOTA_PRO, "team": settings.QUOTA_TEAM}.get(self.tier, 1000)

    @property
    def words_remaining(self):
        return max(0, self.words_limit - self.words_used)

    @property
    def can_process(self):
        return self.status in ("active", "trialing") and self.words_remaining > 0


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=genuuid)
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String(500), default="Untitled")
    section_type = Column(String(50), default="general")
    original_text = Column(Text, default="")
    improved_text = Column(Text, default="")
    mode = Column(String(50), default="enhance")
    source_language = Column(String(10), default="en")
    word_count = Column(Integer, default=0)
    score_before = Column(JSON, default=dict)
    score_after = Column(JSON, default=dict)
    reviewer_alerts = Column(JSON, default=list)
    processing_time_ms = Column(Integer, default=0)
    status = Column(String(20), default="completed")
    created_at = Column(DateTime, default=utcnow)
    user = relationship("User", back_populates="documents")


engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
