import logging
import copy
from fastapi import APIRouter, Depends, Query, HTTPException

from pymongo.database import Database
from typing import List, Dict, Any, Literal, Optional

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)

# --- Re-usable constants ---
CONVICTION_PIPELINE_STAGES = [
    {
        # 1. Filter for only cases that have a final result
        # --- FIX: Changed "Conviction" to "Convicted" ---
        "$match": {"Result": {"$in": ["Convicted", "Acquitted"]}}
    },
    {
        # 2. Group by a placeholder field (to be replaced)
        "$group": {
            "_id": "$GROUP_BY_FIELD_PLACEHOLDER",
            "total_convictions": {
                # --- FIX: Changed "Conviction" to "Convicted" ---
                "$sum": {"$cond": [{"$eq": ["$Result", "Convicted"]}, 1, 0]}
            },
            "total_acquittals": {
                "$sum": {"$cond": [{"$eq": ["$Result", "Acquitted"]}, 1, 0]}
            },
            "total_cases": {"$sum": 1},
        }
    },
    # --- FIX: Add stage to filter out null/empty groupings (fixes unit_name bug) ---
    {"$match": {"_id": {"$ne": None, "$ne": "", "$ne": "N/A"}}},
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
            # --- FEATURE: Added acquittal_rate calculation ---
            "acquittal_rate": {
                "$cond": [
                    {"$eq": ["$total_cases", 0]},
                    0,  # Avoid division by zero
                    {"$divide": ["$total_acquittals", "$total_cases"]},
                ]
            },
        }
    },
    {
        # 4. Sort (placeholder, will be replaced by endpoint)
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
    grouped by a specified category, sorted highest to lowest.
    """

    pipeline = copy.deepcopy(CONVICTION_PIPELINE_STAGES)

    # Dynamically set the group-by field
    pipeline[1]["$group"]["_id"] = f"${group_by}"

    # Rename the projected "category" field for clarity
    pipeline[3]["$project"][group_by] = "$_id"
    pipeline[3]["$project"].pop("category")  # This is now safe

    # Set sort direction
    pipeline[4]["$sort"] = {"conviction_rate": -1}

    try:
        results = list(db["conviction_cases"].aggregate(pipeline))
        return results
    except Exception as e:
        log.error(f"Conviction rate aggregation failed: {e}")
        return []


# --- FEATURE: New Acquittal Rate Endpoint ---
@router.get("/acquittal-rate", summary="Get acquittal rate by category")
async def get_acquittal_rate(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
    group_by: Literal[
        "District", "Court_Name", "Crime_Type", "Sections_of_Law"
    ] = Query("District", description="Category to group by"),
):
    """
    Calculates the acquittal rate (acquittals / (convictions + acquittals))
    grouped by a specified category, sorted highest to lowest.
    """
    pipeline = copy.deepcopy(CONVICTION_PIPELINE_STAGES)

    # Dynamically set the group-by field
    pipeline[1]["$group"]["_id"] = f"${group_by}"

    # Rename the projected "category" field for clarity
    pipeline[3]["$project"][group_by] = "$_id"
    pipeline[3]["$project"].pop("category")

    # Set sort direction
    pipeline[4]["$sort"] = {"acquittal_rate": -1}  # Sort by acquittal rate

    try:
        results = list(db["conviction_cases"].aggregate(pipeline))
        return results
    except Exception as e:
        log.error(f"Acquittal rate aggregation failed: {e}")
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
            "Investigating_Officer": 1,
        }
    }
    duration_calc_stage = {
        "$project": {
            "investigation_duration_ms": {"$subtract": ["$date_cs", "$date_reg"]},
            "trial_duration_ms": {"$subtract": ["$date_judge", "$date_cs"]},
            "total_lifecycle_ms": {"$subtract": ["$date_judge", "$date_reg"]},
            "Investigating_Officer": 1,
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
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
    crime_type: Optional[str] = Query(None, description="Filter trends by Crime_Type"),
    # --- FEATURE: Added Year and Month filters ---
    year: Optional[int] = Query(None, description="Filter by judgement year"),
    month: Optional[int] = Query(None, description="Filter by judgement month"),
):
    """
    Provides time-series data for case outcomes (convictions vs. acquittals)
    grouped by month and year, with an optional filter for Crime_Type.
    """

    match_stage = {
        # --- FIX: Changed "Conviction" to "Convicted" ---
        "Result": {"$in": ["Convicted", "Acquitted"]},
        "judgement_date": {"$ne": None},
    }

    if crime_type:
        match_stage["Crime_Type"] = crime_type

    # --- FEATURE: Add year/month to match logic ---
    if year:
        # Add year to match_stage, ensuring $expr exists if month is also added
        if "$expr" not in match_stage:
            match_stage["$expr"] = {}
        match_stage["$expr"]["$eq"] = [{"$year": "$judgement_date"}, year]

    if month:
        # Add month to match_stage, ensuring $expr exists
        if "$expr" not in match_stage:
            match_stage["$expr"] = {}

        # If year was also specified, we need to $and them
        if "$eq" in match_stage["$expr"]:
            match_stage["$expr"] = {
                "$and": [
                    {"$eq": [{"$year": "$judgement_date"}, year]},
                    {"$eq": [{"$month": "$judgement_date"}, month]},
                ]
            }
        else:
            match_stage["$expr"]["$eq"] = [{"$month": "$judgement_date"}, month]

    pipeline = [
        {"$addFields": {"judgement_date": {"$toDate": "$Date_of_Judgement"}}},
        {"$match": match_stage},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$judgement_date"},
                    "month": {"$month": "$judgement_date"},
                },
                "total_convictions": {
                    # --- FIX: Changed "Conviction" to "Convicted" ---
                    "$sum": {"$cond": [{"$eq": ["$Result", "Convicted"]}, 1, 0]}
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
    group_by: Literal["Investigating_Officer", "Police_Station", "Term_Unit"] = Query(
        "Investigating_Officer", description="Rank by officer, police station, or unit"
    ),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(5, ge=1, le=50, description="Number of records to return"),
):
    """
    Calculates conviction rates grouped by Investigating Officer or Police Station
    to create a performance leaderboard.
    """

    pipeline = copy.deepcopy(CONVICTION_PIPELINE_STAGES)

    # Set sort direction
    pipeline[4]["$sort"] = {"conviction_rate": -1}

    if group_by == "Investigating_Officer":
        pipeline[1]["$group"]["_id"] = {
            "name": "$Investigating_Officer",
            "rank": "$Rank",
        }
        # Project them into the final output
        pipeline[3]["$project"]["officer_name"] = "$_id.name"
        pipeline[3]["$project"]["rank"] = "$_id.rank"

    elif group_by == "Term_Unit":
        pipeline[1]["$group"]["_id"] = "$Term_Unit"
        pipeline[3]["$project"]["unit_name"] = "$_id"

    else:
        # Group by Police Station
        pipeline[1]["$group"]["_id"] = "$Police_Station"
        pipeline[3]["$project"]["police_station"] = "$_id"

    pipeline[3]["$project"].pop("category")
    pipeline.append({"$skip": skip})
    pipeline.append({"$limit": limit})

    try:
        results = list(db["conviction_cases"].aggregate(pipeline))
        return results
    except Exception as e:
        log.error(f"Performance ranking aggregation failed: {e}")
        return []


@router.get(
    "/performance/personnel/{personnel_name}",
    summary="Get a detailed scorecard for an officer",
)
async def get_personnel_scorecard(
    personnel_name: str,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Provides a detailed performance breakdown for a single Investigating Officer.
    """

    match_stage = {"$match": {"Investigating_Officer": personnel_name}}

    date_conversion_stage = {
        "$project": {
            "Result": 1,
            "Delay_Reason": 1,
            "Rank": 1,
            "date_reg": {"$toDate": "$Date_of_Registration"},
            "date_cs": {"$toDate": "$Date_of_Chargesheet"},
        }
    }
    duration_calc_stage = {
        "$project": {
            "Result": 1,
            "Delay_Reason": 1,
            "Rank": 1,
            "investigation_duration_days": {
                "$divide": [
                    {"$subtract": ["$date_cs", "$date_reg"]},
                    1000 * 60 * 60 * 24,
                ]
            },
        }
    }

    group_stage = {
        "$group": {
            "_id": "$Investigating_Officer",
            "rank": {"$first": "$Rank"},
            "total_cases": {"$sum": 1},
            "total_convictions": {
                # --- FIX: Changed "Conviction" to "Convicted" ---
                "$sum": {"$cond": [{"$eq": ["$Result", "Convicted"]}, 1, 0]}
            },
            "total_acquittals": {
                "$sum": {"$cond": [{"$eq": ["$Result", "Acquitted"]}, 1, 0]}
            },
            "avg_investigation_duration_days": {"$avg": "$investigation_duration_days"},
            "acquittal_reasons": {
                "$push": {
                    "$cond": [
                        {"$eq": ["$Result", "Acquitted"]},
                        "$Delay_Reason",
                        "$$REMOVE",  # Don't add nulls
                    ]
                }
            },
        }
    }

    final_project_stage = {
        "$project": {
            "_id": 0,
            "officer_name": "$_id",
            "rank": 1,
            "total_cases": 1,
            "total_convictions": 1,
            "total_acquittals": 1,
            "conviction_rate": {
                "$cond": [
                    {"$eq": ["$total_cases", 0]},
                    0,
                    {"$divide": ["$total_convictions", "$total_cases"]},
                ]
            },
            "avg_investigation_duration_days": {
                "$round": ["$avg_investigation_duration_days", 1]
            },
            "common_acquittal_reasons": "$acquittal_reasons",  # This will be a list
        }
    }

    pipeline = [
        match_stage,
        date_conversion_stage,
        duration_calc_stage,
        group_stage,
        final_project_stage,
    ]

    try:
        result = list(db["conviction_cases"].aggregate(pipeline))
        if not result:
            raise HTTPException(
                status_code=404, detail="Personnel not found or has no cases"
            )

        # Get recent cases
        recent_cases = list(
            db["conviction_cases"]
            .find(
                {"Investigating_Officer": personnel_name},
                {"Case_Number": 1, "Result": 1, "_id": 1},
            )
            .sort("Date_of_Judgement", -1)
            .limit(5)
        )

        # Convert ObjectId
        for case in recent_cases:
            case["id"] = str(case["_id"])
            case.pop("_id")

        final_report = result[0]
        final_report["recent_cases"] = recent_cases

        return final_report

    except Exception as e:
        log.error(f"Personnel scorecard aggregation failed: {e}")
        # Return 500 instead of 200 with error
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/chargesheet-comparison",
    summary="Compare charge-sheeted vs non-charge-sheeted case outcomes",
)
async def get_chargesheet_comparison(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compares outcomes for cases that were chargesheeted vs. not.
    """
    pipeline = [
        {
            "$match": {
                # --- FIX: Changed "Conviction" to "Convicted" ---
                "Result": {"$in": ["Convicted", "Acquitted"]},
                "Date_of_Chargesheet": {"$ne": None, "$exists": True},
            }
        },
        {
            "$addFields": {
                "Chargesheeted_Y_N": {
                    "$cond": [
                        {
                            "$and": [
                                {"$ne": ["$Date_of_Chargesheet", None]},
                                {"$ne": ["$Date_of_Chargesheet", ""]},
                            ]
                        },
                        1,
                        0,
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": "$Chargesheeted_Y_N",
                "total_convictions": {
                    # --- FIX: Changed "Conviction" to "Convicted" ---
                    "$sum": {"$cond": [{"$eq": ["$Result", "Convicted"]}, 1, 0]}
                },
                "total_acquittals": {
                    "$sum": {"$cond": [{"$eq": ["$Result", "Acquitted"]}, 1, 0]}
                },
                "total_cases": {"$sum": 1},
            }
        },
    ]
    try:
        results = list(db["conviction_cases"].aggregate(pipeline))

        # Calculate overall summary
        total_cases = sum(item.get("total_cases", 0) for item in results)
        total_convictions = sum(item.get("total_convictions", 0) for item in results)
        total_acquittals = sum(item.get("total_acquittals", 0) for item in results)

        summary = {
            "total_cases": total_cases,
            "total_convictions": total_convictions,
            "total_acquittals": total_acquittals,
            "overall_conviction_rate": (
                total_convictions / total_cases if total_cases > 0 else 0
            ),
        }

        # Return both summary and grouped data
        return {"summary": summary, "by_group": results}
    except Exception as e:
        log.error(f"Chargesheet comparison aggregation failed: {e}")
        return {"summary": {}, "by_group": []}
