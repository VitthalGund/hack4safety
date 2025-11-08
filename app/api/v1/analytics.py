import logging
import copy
from fastapi import APIRouter, Depends, Query, HTTPException
from pymongo.database import Database
from typing import List, Dict, Any, Literal

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)

# ... (CONVICTION_PIPELINE_STAGES, get_conviction_rate, get_avg_durations, get_case_trends...
# ... all remain unchanged from your existing file) ...
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

    # --- 2. FIX: Use deepcopy to prevent mutating the global constant ---
    pipeline = copy.deepcopy(CONVICTION_PIPELINE_STAGES)

    # Dynamically set the group-by field
    pipeline[1]["$group"]["_id"] = f"${group_by}"

    # Rename the projected "category" field for clarity
    pipeline[2]["$project"][group_by] = "$_id"
    pipeline[2]["$project"].pop("category")  # This is now safe

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
            # Pass through fields needed for duration calc
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
            if key != "_id" and final_result.get(key) is not None:
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

    # --- 2. FIX: Use deepcopy to prevent mutating the global constant ---
    pipeline = copy.deepcopy(CONVICTION_PIPELINE_STAGES)

    if group_by == "Investigating_Officer":
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

    # --- 3. FIX: Un-comment this line. It's now safe and correct. ---
    pipeline[2]["$project"].pop("category")
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

    # --- Pipeline to get conviction stats ---
    match_stage = {"$match": {"Investigating_Officer": personnel_name}}

    # --- Pipeline to get durations ---
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

    # --- Grouping and Projection ---
    group_stage = {
        "$group": {
            "_id": "$Investigating_Officer",
            "rank": {"$first": "$Rank"},
            "total_cases": {"$sum": 1},
            "total_convictions": {
                "$sum": {"$cond": [{"$eq": ["$Result", "Conviction"]}, 1, 0]}
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
        return {"error": str(e)}


@router.get("/chargesheet-comparison", summary="Get data for Sankey diagram")
async def get_chargesheet_comparison(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Provides data formatted for a Sankey diagram, showing the flow from
    'Sections_of_Law' to the final 'Result'.
    """

    links_pipeline = [
        {
            # 1. Filter for only cases that have a final result
            "$match": {"Result": {"$in": ["Conviction", "Acquitted"]}}
        },
        {
            # 2. Split the 'Sections_of_Law' string by comma and space
            # This handles "IPC 302, IPC 379" -> ["IPC 302", "IPC 379"]
            "$project": {
                "Result": 1,
                "sections_array": {"$split": ["$Sections_of_Law", ", "]},
            }
        },
        {
            # 3. Create a separate document for each section in the array
            "$unwind": "$sections_array"
        },
        {
            # 4. Clean up any extra whitespace
            "$project": {
                "Result": 1,
                "section": {"$trim": {"input": "$sections_array"}},
            }
        },
        {
            # 5. Group by the section and the result to get the count
            "$group": {
                "_id": {"source": "$section", "target": "$Result"},
                "value": {"$sum": 1},
            }
        },
        {
            # 6. Format as source/target/value for Sankey links
            "$project": {
                "_id": 0,
                "source": "$_id.source",
                "target": "$_id.target",
                "value": "$value",
            }
        },
        {
            # 7. Sort by value for clarity
            "$sort": {"value": -1}
        },
        {
            # 8. Limit to a reasonable number for visualization
            "$limit": 100
        },
    ]

    try:
        # --- Create Links ---
        links = list(db["conviction_cases"].aggregate(links_pipeline))

        if not links:
            return {"nodes": [], "links": []}

        # --- Generate Nodes ---
        # Get all unique source and target names from the links
        node_names = set()
        for link in links:
            node_names.add(link["source"])
            node_names.add(link["target"])

        # Format as a list of objects
        nodes = [{"id": name} for name in node_names]

        return {"nodes": nodes, "links": links}

    except Exception as e:
        log.error(f"Chargesheet comparison aggregation failed: {e}")
        return {"nodes": [], "links": []}
