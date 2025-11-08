# app.py
from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime
import numpy as np
import joblib
import google.generativeai as genai
import random

# ---------- CONFIG ----------
genai.configure(api_key="AIzaSyDXayr7rJyG2ctbBlsHauigaDf-Vw-OVKk")
model_path = "model/delay_model.pkl"
model = joblib.load(model_path)

# ---------- FASTAPI SETUP ----------
app = FastAPI(title="Delay Category Prediction API")

# ---------- INPUT MODEL ----------
class CaseInput(BaseModel):
    Delay_Reason: str
    Visit_to_Place_of_Occurrence: str
    Date_of_Registration: str

# ---------- HELPER FUNCTIONS ----------
def monte_carlo_decision(delay_days):
    """Implements your 2-day rule + random choice"""
    if delay_days <= 2:
        return "Justified"
    else:
        return np.random.choice(["Negligence", "Logistic issue"], p=[0.5, 0.5])

def generate_reason_gemini(delay_reason, delay_days, result):
    """Gemini-2.5-pro based reason generation"""
    model_g = genai.GenerativeModel("gemini-2.5-pro")
    prompt = f"""
    A case has a delay reason: "{delay_reason}" and a delay of {delay_days} days.
    It was categorized as "{result}".
    Explain briefly (in 2-3 sentences) why this category makes sense, in simple words.
    """
    try:
        response = model_g.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Gemini reason generation failed: {str(e)}"

# ---------- API ROUTE ----------
@app.post("/predict")
def predict_case(data: CaseInput):
    try:
        visit_dt = datetime.strptime(data.Visit_to_Place_of_Occurrence, "%Y-%m-%d")
        reg_dt = datetime.strptime(data.Date_of_Registration, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    delay_days = (reg_dt - visit_dt).days
    delay_days = max(delay_days, 0)

    # Apply Monte Carlo / 2-day logic
    result = monte_carlo_decision(delay_days)

    # Generate AI Reason
    reason = generate_reason_gemini(data.Delay_Reason, delay_days, result)

    return {
        "Delay (days)": delay_days,
        "Predicted_Category": result,
        "Gemini_Reason": reason
    }

# ---------- RUN COMMAND ----------
# uvicorn app:app --reload
