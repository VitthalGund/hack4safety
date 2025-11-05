import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db.session import (
    connect_to_mongo,
    close_mongo_connection,
    connect_to_postgres,
    close_postgres_connection,
)
from app.api.v1 import pqc_endpoints
from app.api.v1 import cases
from app.api.v1 import auth

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Connects to databases on startup and disconnects on shutdown.
    """
    log.info("--- Starting Quantum-Safe Conviction Data Server ---")
    # --- Startup ---
    connect_to_mongo()
    connect_to_postgres()
    await auth.on_startup()

    yield

    log.info("--- Shutting Down Server ---")
    close_mongo_connection()
    await close_postgres_connection()


app = FastAPI(
    title="Quantum-Safe Conviction Data Management System",
    description="API for managing conviction data with PQC for transport security.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(pqc_endpoints.router, prefix="/api/v1/pqc", tags=["PQC Management"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(cases.router, prefix="/api/v1/cases", tags=["Case Management"])


@app.get("/", tags=["Health Check"])
async def read_root():
    """
    Simple health check and instruction route.
    (This replaces the root route from your api_server.py)
    """
    return {
        "status": "Quantum-Safe Conviction Data Server Running.",
        "docs": "/docs",
        "pqc_setup": "/api/v1/pqc/setup",
    }
