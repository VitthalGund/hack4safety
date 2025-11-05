import logging
from fastapi import APIRouter, Depends, Query
from pymongo.database import Database
from typing import List, Dict, Any, Literal

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)

# Define the valid fields for grouping
GroupByField = Literal["District", "Court_Name", "Crime_Type", "Sections_of_Law"]


@router.get("/conviction-rate", summary="Get conviction rate by category")
async def get_conviction_rate(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),  # Protected endpoint
    group_by: GroupByField = Query("District", description="Category to group by"),
):
    """
    Calculates the conviction rate (convictions / (convictions + acquittals))
    grouped by a specified category.
    """

    # This is a MongoDB Aggregation Pipeline
    pipeline = [
        {
            # 1. Filter for only cases that have a final result
            "$match": {"Result": {"$in": ["Conviction", "Acquitted"]}}
        },
        {
            # 2. Group by the user-specified field (e.g., "District")
            "$group": {
                "_id": f"${group_by}",  # The $ denotes a field path
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

    # We must first convert date strings to BSON date objects for calculation
    date_conversion_stage = {
        "$project": {
            "date_reg": {"$toDate": "$Date_of_Registration"},
            "date_cs": {"$toDate": "$Date_of_Chargesheet"},
            "date_judge": {"$toDate": "$Date_of_Judgement"},
        }
    }

    # Calculate durations in milliseconds
    duration_calc_stage = {
        "$project": {
            "investigation_duration_ms": {"$subtract": ["$date_cs", "$date_reg"]},
            "trial_duration_ms": {"$subtract": ["$date_judge", "$date_cs"]},
            "total_lifecycle_ms": {"$subtract": ["$date_judge", "$date_reg"]},
        }
    }

    # Get the global average for all cases
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

        # Round the results for a cleaner output
        final_result = result[0]
        for key in final_result:
            if key != "_id" and final_result[key]:
                final_result[key] = round(final_result[key], 1)

        return final_result

    except Exception as e:
        log.error(f"Duration KPI aggregation failed: {e}")
        return {"error": str(e)}


# TODO: Implement other dashboard endpoints:
# GET /analytics/trends (Trend analysis over time)
# GET /analytics/performance/officers (Performance ranking)
