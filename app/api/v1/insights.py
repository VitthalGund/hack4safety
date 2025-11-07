import logging
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/correlation", summary="Get AI-based correlation for case outcomes")
async def get_ai_correlation(
    db: Database = Depends(get_mongo_db), current_user: User = Depends(get_current_user)
):
    """
    AI-based correlation between investigation quality and conviction outcomes.

    This endpoint:
    1. Fetches all case data from MongoDB.
    2. Uses Pandas to clean and prepare the data.
    3. Uses scikit-learn to train a logistic regression model.
    4. Returns the factors most correlated with 'Conviction'.
    """

    # 1. Fetch data from MongoDB
    collection = db["conviction_cases"]
    cases_cursor = collection.find(
        {"Result": {"$in": ["Conviction", "Acquitted"]}},
        {
            # Select only the fields we need for analysis
            "Result": 1,
            "District": 1,
            "Rank": 1,  # Investigating Officer's Rank
            "Nature_of_Offence": 1,
            "Duration_of_Trial_days": 1,
            "Crime_Type": 1,
        },
    )

    data = list(cases_cursor)
    if len(data) < 20:  # Need minimum data to train
        raise HTTPException(
            status_code=400,
            detail=f"Not enough data for analysis (found {len(data)} records, need at least 20).",
        )

    # 2. Use Pandas to prepare data
    df = pd.DataFrame(data)

    # Drop rows with missing values
    df = df.dropna()

    if df.empty:
        raise HTTPException(
            status_code=400, detail="No complete data available for analysis."
        )

    # Convert target variable: 'Conviction' = 1, 'Acquitted' = 0
    df["target"] = (df["Result"] == "Conviction").astype(int)

    # Define features
    # Categorical features will be one-hot encoded
    categorical_features = ["District", "Rank", "Nature_of_Offence", "Crime_Type"]
    # Numerical features will be used as-is
    numerical_features = ["Duration_of_Trial_days"]

    # 3. Use scikit-learn for one-hot encoding
    try:
        encoder = OneHotEncoder(handle_unknown="ignore")
        X_categorical = encoder.fit_transform(df[categorical_features])
        X_numerical = df[numerical_features]

        # Combine numerical and encoded categorical features
        X = pd.concat(
            [
                pd.DataFrame(
                    X_categorical.toarray(), columns=encoder.get_feature_names_out()
                ),
                X_numerical.reset_index(drop=True),
            ],
            axis=1,
        )
        y = df["target"]
    except Exception as e:
        log.error(f"Data processing error: {e}")
        raise HTTPException(status_code=500, detail=f"Data processing error: {e}")

    # 4. Train a Logistic Regression model
    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)

    # 5. Get the correlations (coefficients)
    coefficients = model.coef_[0]
    feature_names = X.columns

    # Create a DataFrame of features and their importance
    corr_df = pd.DataFrame({"feature": feature_names, "coefficient": coefficients})

    # Add absolute value for sorting
    corr_df["abs_coefficient"] = corr_df["coefficient"].abs()

    # Sort by importance
    corr_df = corr_df.sort_values(by="abs_coefficient", ascending=False)

    # 6. Format the output
    positive_correlations = corr_df[corr_df["coefficient"] > 0].head(5)
    negative_correlations = corr_df[corr_df["coefficient"] < 0].head(5)
    print(
        {
            "analysis_status": "Completed",
            "records_analyzed": len(df),
            "factors_promoting_conviction": positive_correlations.to_dict("records"),
            "factors_promoting_acquittal": negative_correlations.to_dict("records"),
        }
    )
    return {
        "analysis_status": "Completed",
        "records_analyzed": len(df),
        "factors_promoting_conviction": positive_correlations.to_dict("records"),
        "factors_promoting_acquittal": negative_correlations.to_dict("records"),
    }
