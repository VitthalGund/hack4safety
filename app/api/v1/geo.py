import logging
from fastapi import APIRouter, Depends, Query
from pymongo.database import Database
from typing import List, Optional, Dict, Any

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User, UserRole

router = APIRouter()
log = logging.getLogger(__name__)


# --- Helper: Query Builder (re-used from cases.py) ---
def _build_filter_query(
    current_user: User,
    district: Optional[str],
    sections_of_law: Optional[str],
    result: Optional[str],
) -> dict:

    query: Dict[str, Any] = {}
    if sections_of_law:
        query["Sections_of_Law"] = {"$regex": sections_of_law, "$options": "i"}
    if district:
        query["District"] = district
    if result:
        query["Result"] = result

    # Apply role-based filtering
    if current_user.role == UserRole.SP:
        if district and district != current_user.district:
            # Return a query that finds nothing
            return {"_id": None}
        query["District"] = current_user.district
    elif current_user.role == UserRole.IIC:
        query["Police_Station"] = current_user.police_station

    return query


# --- Endpoints ---


@router.get("/cases", summary="Get cases as GeoJSON features")
async def get_geo_cases(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
    district: Optional[str] = Query(None),
    sections_of_law: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
):
    """
    Provides a GeoJSON FeatureCollection of cases for map display.
    Requires 'latitude' and 'longitude' fields in the data.
    """

    query = _build_filter_query(current_user, district, sections_of_law, result)

    # Ensure we only get cases with valid coordinates
    query.update(
        {
            "latitude": {"$exists": True, "$ne": None},
            "longitude": {"$exists": True, "$ne": None},
        }
    )

    cases = list(db["conviction_cases"].find(query).limit(500))  # Limit to 500 for maps

    # Format as GeoJSON
    features = []
    for case in cases:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [case["longitude"], case["latitude"]],
                },
                "properties": {
                    "id": str(case["_id"]),
                    "case_number": case.get("Case_Number"),
                    "result": case.get("Result"),
                    "sections": case.get("Sections_of_Law"),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


@router.get("/heatmap", summary="Get data for a heatmap layer")
async def get_heatmap_data(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
    district: Optional[str] = Query(None),
    sections_of_law: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
):
    """
    Provides a simple list of lat/lng/intensity for a heatmap.
    """

    query = _build_filter_query(current_user, district, sections_of_law, result)
    query.update(
        {
            "latitude": {"$exists": True, "$ne": None},
            "longitude": {"$exists": True, "$ne": None},
        }
    )

    projection = {"latitude": 1, "longitude": 1, "_id": 0}
    cases = list(db["conviction_cases"].find(query, projection).limit(2000))

    # Format for a simple heatmap library
    return [
        {"lat": c["latitude"], "lng": c["longitude"], "intensity": 1} for c in cases
    ]
