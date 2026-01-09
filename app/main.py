import logging
import os
import random
from datetime import datetime

import google.generativeai as genai
import joblib
import numpy as np
from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

from app.api.v1 import (
    accused,
    admin,
    alerts,
    analytics,
    auth,
    cases,
    geo,
    insights,
    metadata,
    pqc_endpoints,
    rag,
    reports,
)
from app.db.session import (
    connect_to_mongo,
    close_mongo_connection,
    connect_to_postgres,
    close_postgres_connection,
)

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
    title="Quantum-Safe Conviction Data Management API",
    description="API for managing and analyzing conviction data with PQC.",
    version="1.0.0",
)

# --- ADDED: Delay Prediction Config & Model Loading ---
# WARNING: Hardcoding API keys is a major security risk.
# Use environment variables (like your settings.py) instead.
GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY", "AIzaSyDXayr7rJyG2ctbBlsHauigaDf-Vw-OVKk"
)
genai.configure(api_key=GEMINI_API_KEY)

# --- FIX: Corrected model path relative to this file (app/main.py) ---
MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "../delay_prediction1/model/delay_model.pkl"
)
delay_model = None

try:
    delay_model = joblib.load(MODEL_PATH)
    log.info(f"Delay prediction model loaded successfully from {MODEL_PATH}")
except Exception as e:
    log.error(f"FATAL: Could not load delay_model.pkl. Error: {e}")
    # The app will run, but /predict endpoint will fail.
# ---------------------------------------------------


# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


# --- Lifespan Events ---
@app.on_event("startup")
def startup_event():
    connect_to_mongo()
    connect_to_postgres()


@app.on_event("shutdown")
async def shutdown_event():
    close_mongo_connection()
    await close_postgres_connection()


# --- API Routers ---
v1_router = APIRouter()
v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
v1_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
v1_router.include_router(cases.router, prefix="/cases", tags=["Cases"])
v1_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
v1_router.include_router(accused.router, prefix="/accused", tags=["Accused"])
v1_router.include_router(geo.router, prefix="/geo", tags=["Geographic"])
v1_router.include_router(metadata.router, prefix="/metadata", tags=["Metadata"])
v1_router.include_router(rag.router, prefix="/rag", tags=["RAG AI Service"])
v1_router.include_router(alerts.router, prefix="/alerts", tags=["Alerts"])
v1_router.include_router(insights.router, prefix="/insights", tags=["AI Insights"])
v1_router.include_router(pqc_endpoints.router, prefix="/pqc", tags=["PQC Simulator"])
v1_router.include_router(reports.router, prefix="/reports", tags=["Reports"])


# --- ADDED: Delay Prediction Models & Helpers ---
class CaseInput(BaseModel):
    Delay_Reason: str
    Visit_to_Place_of_Occurrence: str
    Date_of_Registration: str


def monte_carlo_decision(delay_days):
    """Implements your 2-day rule + random choice"""
    if delay_days <= 2:
        return "Justified"
    else:
        return np.random.choice(["Negligence", "Logistic issue"], p=[0.5, 0.5])


def generate_reason_gemini(delay_reason, delay_days, result):
    """Gemini-based reason generation"""
    if not GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY not set. Skipping reason generation.")
        return "Reason generation skipped: API key not configured."

    try:
        model_g = genai.GenerativeModel("gemini-pro")  # Use standard "gemini-pro"
        prompt = f"""
        A case has a delay reason: "{delay_reason}" and a delay of {delay_days} days.
        It was categorized as "{result}".
        Explain briefly (in 2-3 sentences) why this category makes sense, in simple words.
        """
        response = model_g.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        log.error(f"Gemini reason generation failed: {e}")
        # Return a structured error
        return f"Gemini reason generation failed. Details: {str(e)}"


# ------------------------------------------------


# --- ADDED: Delay Prediction API Route to v1_router ---
@v1_router.post("/predict", summary="Predicts case delay category")
def predict_case(data: CaseInput):
    if delay_model is None:
        raise HTTPException(
            status_code=503, detail="Delay prediction model is not loaded."
        )

    try:
        visit_dt = datetime.strptime(data.Visit_to_Place_of_Occurrence, "%Y-%m-%d")
        reg_dt = datetime.strptime(data.Date_of_Registration, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

    delay_days = (reg_dt - visit_dt).days
    delay_days = max(delay_days, 0)

    # CRITIQUE: The loaded 'delay_model' is NOT used here.
    # Your logic only uses the Monte Carlo function.
    result = monte_carlo_decision(delay_days)

    # Generate AI Reason
    reason = generate_reason_gemini(data.Delay_Reason, delay_days, result)

    return {
        "Delay (days)": delay_days,
        "Predicted_Category": result,
        "Gemini_Reason": reason,
    }


# ----------------------------------------------------


app.include_router(v1_router, prefix="/api/v1")


@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Quantum-Safe Conviction Data Management API"}
