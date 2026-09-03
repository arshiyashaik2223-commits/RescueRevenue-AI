"""
app/main.py
FastAPI application entrypoint — registers all routers, wires DB
lifecycle, exception handlers, and CORS.

Run locally with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    analytics_routes,
    auth_routes,
    copilot_routes,
    failed_payment_routes,
    recovery_prediction_routes,
    transaction_routes,
    webhook_routes,
)
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.database import close_mongo_connection, connect_to_mongo

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s (%s)", settings.APP_NAME, settings.APP_ENV)
    await connect_to_mongo()
    yield
    await close_mongo_connection()
    logger.info("Shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.APP_DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(auth_routes.router, prefix=settings.API_V1_PREFIX)
app.include_router(transaction_routes.router, prefix=settings.API_V1_PREFIX)
app.include_router(failed_payment_routes.router, prefix=settings.API_V1_PREFIX)
app.include_router(recovery_prediction_routes.router, prefix=settings.API_V1_PREFIX)
app.include_router(copilot_routes.router, prefix=settings.API_V1_PREFIX)
app.include_router(analytics_routes.router, prefix=settings.API_V1_PREFIX)
app.include_router(webhook_routes.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}
