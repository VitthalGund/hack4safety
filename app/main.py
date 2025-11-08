import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.db.session import (
    connect_to_mongo,
    close_mongo_connection,
    connect_to_postgres,
    close_postgres_connection,
)

# Import all routers
from app.api.v1 import pqc_endpoints
from app.api.v1 import cases
from app.api.v1 import auth
from app.api.v1 import analytics
from app.api.v1 import insights
from app.api.v1 import admin
from app.api.v1 import accused
from app.api.v1 import geo
from app.api.v1 import alerts
from app.api.v1 import metadata
from app.api.v1 import rag

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

# --- 2. ADD CORS MIDDLEWARE ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allows all headers
)

app.include_router(pqc_endpoints.router, prefix="/api/v1/pqc", tags=["PQC Management"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(cases.router, prefix="/api/v1/cases", tags=["Case Management"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(insights.router, prefix="/api/v1/insights", tags=["AI Insights"])
app.include_router(rag.router, prefix="/api/v1/rag", tags=["RAG Legal Bot"])
app.include_router(metadata.router, prefix="/api/v1/metadata", tags=["Metadata"])

# --- NEW ROUTERS ---
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(accused.router, prefix="/api/v1/accused", tags=["Accused 360"])
app.include_router(geo.router, prefix="/api/v1/geo", tags=["Geospatial"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])


@app.get("/", tags=["Health Check"])
async def read_root():
    """
    Simple health check and instruction route.
    """
    return {
        "status": "Quantum-Safe Conviction Data Server Running.",
        "docs": "/docs",
        "pqc_setup": "/api/v1/pqc/setup",
    }
