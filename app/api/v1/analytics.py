import logging
from fastapi import APIRouter, Depends, Query
from pymongo.database import Database
from typing import List, Dict, Any, Literal

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)

# --- Re-usable constants ---
CONVICTION_PIPELINE_STAGES = [
    {
        # 1. Filter for only cases that have a final result
        "$match": {"Result": {"$in": ["Conviction", "Acquitted"]}}
    },
    {
        # 2. Group by a placeholder field (to be replaced)
        "$group": {
            "_id": "$GROUP_BY_FIELD_PLACEHOLDER",
            "total_convictions": {
                "$sum": {"$cond": [{"$eq": ["$Result", "Conviction"]}, 1, 0]}
            },
            "total_acquittals": {
                "$sum": {"$cond": [{"$eq": ["$Result", "Acquitted"]}, 1, 0]}
            },
            "total_cases": {"$sum": 1},
        }
    },
    {
        # 3. Calculate the rate
        "$project": {
            "category": "$_id",
            "total_convictions": 1,
            "total_acquittals": 1,
            "total_cases": 1,
            "conviction_rate": {
                "$cond": [
                    {"$eq": ["$total_cases", 0]},
                    0,  # Avoid division by zero
                    {"$divide": ["$total_convictions", "$total_cases"]},
                ]
            },
        }
    },
    {
        # 4. Sort by the highest conviction rate
        "$sort": {"conviction_rate": -1}
    },
    {"$limit": 50},  # Limit to top 50 results
]

# --- Endpoints ---


@router.get("/conviction-rate", summary="Get conviction rate by category")
async def get_conviction_rate(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
    group_by: Literal[
        "District", "Court_Name", "Crime_Type", "Sections_of_Law"
    ] = Query("District", description="Category to group by"),
):
    """
    Calculates the conviction rate (convictions / (convictions + acquittals))
    grouped by a specified category.
    """

    # Create a deep copy of the pipeline to avoid modifying the original
    pipeline = [stage.copy() for stage in CONVICTION_PIPELINE_STAGES]

    # Dynamically set the group-by field
    pipeline[1]["$group"]["_id"] = f"${group_by}"

    # Rename the projected "category" field for clarity
    pipeline[2]["$project"][group_by] = "$_id"
    pipeline[2]["$project"].pop("category")

    try:
        results = list(db["conviction_cases"].aggregate(pipeline))
        return results
    except Exception as e:
        log.error(f"Analytics aggregation failed: {e}")
        return []


@router.get("/kpi/durations", summary="Get average case durations")
async def get_avg_durations(
    db: Database = Depends(get_mongo_db), current_user: User = Depends(get_current_user)
):
    """
    Calculates high-level KPIs:
    - Avg. Investigation Duration (Registration to Chargesheet)
    - Avg. Trial Duration (Chargesheet to Judgement)
    - Avg. Total Case Lifecycle (Registration to Judgement)
    """
    date_conversion_stage = {
        "$project": {
            "date_reg": {"$toDate": "$Date_of_Registration"},
            "date_cs": {"$toDate": "$Date_of_Chargesheet"},
            "date_judge": {"$toDate": "$Date_of_Judgement"},
        }
    }
    duration_calc_stage = {
        "$project": {
            "investigation_duration_ms": {"$subtract": ["$date_cs", "$date_reg"]},
            "trial_duration_ms": {"$subtract": ["$date_judge", "$date_cs"]},
            "total_lifecycle_ms": {"$subtract": ["$date_judge", "$date_reg"]},
        }
    }
    average_stage = {
        "$group": {
            "_id": None,
            "avg_investigation_days": {
                "$avg": {"$divide": ["$investigation_duration_ms", 1000 * 60 * 60 * 24]}
            },
            "avg_trial_days": {
                "$avg": {"$divide": ["$trial_duration_ms", 1000 * 60 * 60 * 24]}
            },
            "avg_lifecycle_days": {
                "$avg": {"$divide": ["$total_lifecycle_ms", 1000 * 60 * 60 * 24]}
            },
        }
    }
    pipeline = [date_conversion_stage, duration_calc_stage, average_stage]
    try:
        result = list(db["conviction_cases"].aggregate(pipeline))
        if not result:
            return {"error": "No data to calculate."}
        final_result = result[0]
        for key in final_result:
            if key != "_id" and final_result[key]:
                final_result[key] = round(final_result[key], 1)
        return final_result
    except Exception as e:
        log.error(f"Duration KPI aggregation failed: {e}")
        return {"error": str(e)}


@router.get("/trends", summary="Get conviction/acquittal trends over time")
async def get_case_trends(
    db: Database = Depends(get_mongo_db), current_user: User = Depends(get_current_user)
):
    """
    Provides time-series data for case outcomes (convictions vs. acquittals)
    grouped by month and year.
    """
    pipeline = [
        {"$addFields": {"judgement_date": {"$toDate": "$Date_of_Judgement"}}},
        {
            "$match": {
                "Result": {"$in": ["Conviction", "Acquitted"]},
                "judgement_date": {"$ne": None},
            }
        },
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$judgement_date"},
                    "month": {"$month": "$judgement_date"},
                },
                "total_convictions": {
                    "$sum": {"$cond": [{"$eq": ["$Result", "Conviction"]}, 1, 0]}
                },
                "total_acquittals": {
                    "$sum": {"$cond": [{"$eq": ["$Result", "Acquitted"]}, 1, 0]}
                },
                "total_cases": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                "year": "$_id.year",
                "month": "$_id.month",
                "total_convictions": 1,
                "total_acquittals": 1,
                "total_cases": 1,
            }
        },
        {"$sort": {"year": 1, "month": 1}},
    ]
    try:
        results = list(db["conviction_cases"].aggregate(pipeline))
        return results
    except Exception as e:
        log.error(f"Trends aggregation failed: {e}")
        return []


@router.get(
    "/performance/ranking", summary="Get performance ranking for officers or units"
)
async def get_performance_ranking(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
    group_by: Literal["Investigating_Officer", "Police_Station"] = Query(
        "Investigating_Officer", description="Rank by officer or police station"
    ),
):
    """
    Calculates conviction rates grouped by Investigating Officer or Police Station
    to create a performance leaderboard.
    """

    # Create a deep copy of the pipeline
    pipeline = [stage.copy() for stage in CONVICTION_PIPELINE_STAGES]

    if group_by == "Investigating_Officer":
        # Group by both officer name and rank
        pipeline[1]["$group"]["_id"] = {
            "name": "$Investigating_Officer",
            "rank": "$Rank",
        }
        # Project them into the final output
        pipeline[2]["$project"]["officer_name"] = "$_id.name"
        pipeline[2]["$project"]["rank"] = "$_id.rank"
    else:
        # Group by Police Station
        pipeline[1]["$group"]["_id"] = "$Police_Station"
        pipeline[2]["$project"]["police_station"] = "$_id"

    pipeline[2]["$project"].pop("category")

    try:
        results = list(db["conviction_cases"].aggregate(pipeline))
        return results
    except Exception as e:
        log.error(f"Performance ranking aggregation failed: {e}")
        return []
