import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import Base, engine

# Import models so they are registered on Base.metadata before create_all.
from app import models  # noqa: F401
from app.routers import audit, cases, health, meta, patterns, projects, risk

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Simple schema management: create tables if they don't exist (no Alembic).
    # On managed platforms the DB may still be recovering when the app boots, so
    # retry rather than crash-loop; if it never comes up, start anyway and let
    # individual requests surface the error (health check will report "down").
    for attempt in range(1, 13):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables ensured.")
            break
        except OperationalError as exc:
            wait = min(5 * attempt, 30)
            logger.warning("DB not ready (attempt %d): %s — retrying in %ds", attempt, exc, wait)
            time.sleep(wait)
    else:
        logger.error("DB still unreachable after retries; starting API anyway.")
    yield


app = FastAPI(
    title="MPLAD Anomaly & Fraud Detection API",
    description="Prototype for SIH26102 (MoSPI). Flags suspicious MPLAD projects "
    "with plain-language explanations.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(meta.router)
app.include_router(projects.router)
app.include_router(risk.router)
app.include_router(patterns.router)
app.include_router(audit.router)
app.include_router(cases.router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "mplad-fraud-detection", "docs": "/docs", "health": "/health"}
