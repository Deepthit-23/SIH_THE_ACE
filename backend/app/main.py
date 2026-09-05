import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine

# Import models so they are registered on Base.metadata before create_all.
from app import models  # noqa: F401
from app.routers import health, projects

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Hackathon-simple schema management: create tables if they don't exist.
    # (No Alembic migrations for this prototype.)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured.")
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
app.include_router(projects.router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "mplad-fraud-detection", "docs": "/docs", "health": "/health"}
