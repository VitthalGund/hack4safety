# # import pandas as pd
# # import numpy as np
# # import joblib
# # from sklearn.model_selection import train_test_split
# # from sklearn.ensemble import RandomForestClassifier
# # from sklearn.feature_extraction.text import TfidfVectorizer
# # from sklearn.pipeline import Pipeline
# # from sklearn.compose import ColumnTransformer
# # from sklearn.preprocessing import StandardScaler
# # from sklearn.metrics import classification_report
# # from datetime import datetime

# # df = pd.read_csv("odisha_conviction_dataset_v6.csv")
# # df = df.dropna(subset=["Delay_Reason", "Date_of_Registration", "Visit_to_Place_of_Occurrence"])
# # df["Date_of_Registration"] = pd.to_datetime(df["Date_of_Registration"], errors="coerce")
# # df["Visit_to_Place_of_Occurrence"] = pd.to_datetime(df["Visit_to_Place_of_Occurrence"], errors="coerce")
# # df["delay_days"] = (df["Date_of_Registration"] - df["Visit_to_Place_of_Occurrence"]).dt.days.clip(lower=0)
# # df["Delay_Category"] = pd.cut(
# #     df["delay_days"],
# #     bins=[-1, 2, 7, np.inf],
# #     labels=["Justified", "Negligence", "Logistic issue"]
# # )

# # X = df[["Delay_Reason", "delay_days"]]
# # y = df["Delay_Category"]

# # X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# # text_transformer = TfidfVectorizer(max_features=2000, stop_words="english")
# # num_transformer = StandardScaler()

# # preprocessor = ColumnTransformer([
# #     ("tfidf", text_transformer, "Delay_Reason"),
# #     ("scaler", num_transformer, ["delay_days"])
# # ])

# # model = Pipeline([
# #     ("preprocess", preprocessor),
# #     ("classifier", RandomForestClassifier(n_estimators=200, random_state=42))
# # ])

# # model.fit(X_train, y_train)
# # y_pred = model.predict(X_test)
# # print(classification_report(y_test, y_pred))

# # joblib.dump(model, "model/delay_model.pkl")



# import pandas as pd
# import numpy as np
# import random
# import joblib
# from sklearn.model_selection import train_test_split
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.preprocessing import StandardScaler
# from sklearn.compose import ColumnTransformer
# from sklearn.ensemble import RandomForestClassifier
# from sklearn.pipeline import Pipeline
# from sklearn.metrics import classification_report
# from datetime import datetime
# import google.generativeai as genai

# # Configure Gemini API
# genai.configure(api_key="AIzaSyDXayr7rJyG2ctbBlsHauigaDf-Vw-OVKk")

# # Load and preprocess data
# df = pd.read_csv("odisha_conviction_dataset_v6.csv")
# df = df.dropna(subset=["Delay_Reason", "Date_of_Registration", "Visit_to_Place_of_Occurrence"])

# df["Date_of_Registration"] = pd.to_datetime(df["Date_of_Registration"], errors="coerce")
# df["Visit_to_Place_of_Occurrence"] = pd.to_datetime(df["Visit_to_Place_of_Occurrence"], errors="coerce")

# df["delay_days"] = (df["Date_of_Registration"] - df["Visit_to_Place_of_Occurrence"]).dt.days.clip(lower=0)
# df["Delay_Category"] = pd.cut(
#     df["delay_days"],
#     bins=[-1, 2, 7, np.inf],
#     labels=["Justified", "Negligence", "Logistic issue"]
# )

# X = df[["Delay_Reason", "delay_days"]]
# y = df["Delay_Category"]

# X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# # ML pipeline (we still train a baseline model, but prediction logic is overridden later)
# text_transformer = TfidfVectorizer(max_features=2000, stop_words="english")
# num_transformer = StandardScaler()

# preprocessor = ColumnTransformer([
#     ("tfidf", text_transformer, "Delay_Reason"),
#     ("scaler", num_transformer, ["delay_days"])
# ])

# model = Pipeline([
#     ("preprocess", preprocessor),
#     ("classifier", RandomForestClassifier(n_estimators=200, random_state=42))
# ])

# model.fit(X_train, y_train)
# y_pred = model.predict(X_test)
# print(classification_report(y_test, y_pred))

# joblib.dump(model, "model/delay_model.pkl")

# # ---- Monte Carlo Simulation / Randomized Prediction Logic ----
# def monte_carlo_prediction(delay_days, delay_reason):
#     """Predicts based on random sampling logic."""
#     if delay_days <= 2:
#         result = "Justified"
#     else:
#         result = np.random.choice(["Negligence", "Logistic issue"], p=[0.5, 0.5])
#     return result

# def generate_reason_gemini(delay_reason, delay_days, category):
#     """Uses Gemini 2.5 Pro to explain the prediction."""
#     model_g = genai.GenerativeModel("gemini-2.5-pro")
#     prompt = f"""
#     Given the delay reason "{delay_reason}" and the delay of {delay_days} days,
#     the case was classified as "{category}".
#     Generate a concise explanation (2–3 sentences) on why this classification was made.
#     """
#     try:
#         response = model_g.generate_content(prompt)
#         return response.text.strip()
#     except Exception as e:
#         return f"Explanation generation failed: {e}"

# # ---- Interactive prediction demo ----
# def predict_case(delay_reason, visit_date, registration_date):
#     visit_dt = datetime.strptime(visit_date, "%Y-%m-%d")
#     reg_dt = datetime.strptime(registration_date, "%Y-%m-%d")
#     delay_days = (reg_dt - visit_dt).days
#     delay_days = max(delay_days, 0)

#     category = monte_carlo_prediction(delay_days, delay_reason)
#     reason = generate_reason_gemini(delay_reason, delay_days, category)

#     return {
#         "Delay (days)": delay_days,
#         "Predicted Category": category,
#         "AI Reason": reason
#     }

# # ---- Example usage ----
# if __name__ == "__main__":
#     test_case = {
#         "Delay_Reason": "Due to communication issues and late witness arrival",
#         "Visit_to_Place_of_Occurrence": "2016-09-25",
#         "Date_of_Registration": "2017-11-30"
#     }

#     result = predict_case(
#         test_case["Delay_Reason"],
#         test_case["Visit_to_Place_of_Occurrence"],
#         test_case["Date_of_Registration"]
#     )

#     print("\n----- Case Prediction -----")
#     for k, v in result.items():
#         print(f"{k}: {v}")



# train_model.py
import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from datetime import datetime
import os

os.makedirs("model", exist_ok=True)

# Load data
df = pd.read_csv("odisha_conviction_dataset_v6.csv")

# Clean missing values
df = df.dropna(subset=["Delay_Reason", "Date_of_Registration", "Visit_to_Place_of_Occurrence"])

# Convert to datetime
df["Date_of_Registration"] = pd.to_datetime(df["Date_of_Registration"], errors="coerce")
df["Visit_to_Place_of_Occurrence"] = pd.to_datetime(df["Visit_to_Place_of_Occurrence"], errors="coerce")

# Calculate delay
df["delay_days"] = (df["Date_of_Registration"] - df["Visit_to_Place_of_Occurrence"]).dt.days.clip(lower=0)

# Categorize
df["Delay_Category"] = pd.cut(
    df["delay_days"],
    bins=[-1, 2, 7, np.inf],
    labels=["Justified", "Negligence", "Logistic issue"]
)

X = df[["Delay_Reason", "delay_days"]]
y = df["Delay_Category"]

# Split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# Preprocessor
text_transformer = TfidfVectorizer(max_features=2000, stop_words="english")
num_transformer = StandardScaler()

preprocessor = ColumnTransformer([
    ("tfidf", text_transformer, "Delay_Reason"),
    ("scaler", num_transformer, ["delay_days"])
])

# Model
model = Pipeline([
    ("preprocess", preprocessor),
    ("classifier", RandomForestClassifier(n_estimators=200, random_state=42))
])

# Train
model.fit(X_train, y_train)

# Save
joblib.dump(model, "model/delay_model.pkl")

print("✅ Model trained and saved at model/delay_model.pkl")
