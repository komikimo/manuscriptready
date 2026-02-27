"""ManuscriptReady — Main Application"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from app.core.config import settings
from app.models.database import init_db
from app.api.routes import auth, billing as legacy_billing, process, dash, journal, ver, fb, analytics_router, eval_router
from app.api import saas
from app.api.billing import router as billing_router
from app.api.stripe_webhook import router as webhook_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("ManuscriptReady API started")
    yield


app = FastAPI(title="ManuscriptReady API", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
for r in [auth, process, dash, journal, ver, fb, analytics_router, eval_router, saas.router]:
    app.include_router(r, prefix=settings.API_PREFIX)

# Billing + Stripe webhook (no API prefix — Stripe sends to /stripe/webhook)
app.include_router(billing_router, prefix=settings.API_PREFIX)
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "3.0.0"}
