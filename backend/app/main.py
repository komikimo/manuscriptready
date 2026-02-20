"""ManuscriptReady — Main Application"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from app.core.config import settings
from app.models.database import init_db
from app.api.routes import auth, billing, process, dash

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="ManuscriptReady API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
for r in [auth, billing, process, dash]:
    app.include_router(r, prefix=settings.API_PREFIX)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "ManuscriptReady", "version": "2.0.0"}
