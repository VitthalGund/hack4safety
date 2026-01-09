import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from pymongo.database import Database
from typing import List, Optional, Dict, Any

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User, UserRole

router = APIRouter()
log = logging.getLogger(__name__)


# --- Helper to build role-based query ---
def get_role_query(current_user: User) -> dict:
    query = {}
    if current_user.role == UserRole.SP:
        query["District"] = current_user.district
    elif current_user.role == UserRole.IIC:
        query["Police_Station"] = current_user.police_station
    return query


# --- Endpoints ---


@router.get("/search", summary="Search for an accused person")
async def search_accused(
    q: str = Query(..., min_length=3, description="Search query for accused name"),
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Searches for accused persons by name and returns a summary.
    """

    role_query = get_role_query(current_user)
    search_query = {"Accused_Name": {"$regex": q, "$options": "i"}, **role_query}

    pipeline = [
        {"$match": search_query},
        {
            "$group": {
                "_id": "$Accused_Name",
                "aliases": {"$addToSet": "$Accused_Alias"},
                "case_count": {"$sum": 1},
                "last_case_result": {"$last": "$Result"},
            }
        },
        {
            "$project": {
                "id": "$_id",
                "name": "$_id",
                "alias": {"$first": "$aliases"},  # Show one alias
                "case_count": 1,
                "last_case_result": 1,
                "_id": 0,
            }
        },
        {"$limit": 20},
    ]

    results = list(db["conviction_cases"].aggregate(pipeline))
    return results


@router.get("/{accused_name}", summary="Get a 360-degree profile of an accused")
async def get_accused_profile(
    accused_name: str,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Provides a detailed profile for a single accused person,
    including their case history and conviction status.
    """

    role_query = get_role_query(current_user)
    search_query = {"Accused_Name": accused_name, **role_query}

    case_history = list(
        db["conviction_cases"].find(
            search_query,
            {"Case_Number": 1, "Result": 1, "Sections_of_Law": 1, "_id": 0},
        )
    )

    if not case_history:
        raise HTTPException(
            status_code=404, detail="Accused not found or not in your jurisdiction"
        )

    conviction_count = 0
    acquittal_count = 0
    for case in case_history:
        if case.get("Result") == "Conviction":
            conviction_count += 1
        elif case.get("Result") == "Acquitted":
            acquittal_count += 1

    is_habitual_offender = conviction_count > 1

    return {
        "name": accused_name,
        "conviction_count": conviction_count,
        "acquittal_count": acquittal_count,
        "total_cases": len(case_history),
        "is_habitual_offender": is_habitual_offender,
        "case_history": case_history,
    }


@router.get("/{accused_name}/network", summary="Get a co-accused network graph")
async def get_accused_network(
    accused_name: str,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Builds a node-link graph of co-accused individuals.
    (Assumes a 'Co_Accused' array field in the data)
    """

    role_query = get_role_query(current_user)
    search_query = {"Accused_Name": accused_name, **role_query}

    cases = list(db["conviction_cases"].find(search_query, {"Co_Accused": 1, "_id": 0}))

    if not cases:
        raise HTTPException(
            status_code=404, detail="Accused not found or not in your jurisdiction"
        )

    nodes = [{"id": accused_name, "name": accused_name}]
    links = []
    node_ids = {accused_name}

    for case in cases:
        if "Co_Accused" in case and isinstance(case["Co_Accused"], list):
            for co_accused_name in case["Co_Accused"]:
                if co_accused_name not in node_ids:
                    nodes.append({"id": co_accused_name, "name": co_accused_name})
                    node_ids.add(co_accused_name)

                # Add link
                links.append({"source": accused_name, "target": co_accused_name})

    return {"nodes": nodes, "links": links}
