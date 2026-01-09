import logging
import asyncio
from fastapi import APIRouter, Depends, Query, HTTPException
from pymongo.database import Database
from typing import List, Literal

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)

# Define the allowed fields for security
ValidField = Literal[
    "District",
    "Police_Station",
    "Court_Name",
    "Investigating_Officer",
    "Rank",
    "Crime_Type",
    "Result",
    "Sections_of_Law",
    "PP_Name",
    "Judge_Name",
]


# --- Refactored callable function ---
async def get_distinct_values(
    field_name: ValidField, db: Database, current_user: User
) -> List[str]:
    """
    Get a list of all unique, non-null values for a given field.
    (Callable by other endpoints)
    """
    try:
        collection = db["conviction_cases"]
        # Use the distinct command on the specified field
        # Note: distinct is not async, so we don't await
        values = collection.distinct(field_name)

        # Filter out any null/empty values
        results = [str(val) for val in values if val]
        results.sort()

        return results
    except Exception as e:
        log.error(f"Failed to get distinct values for {field_name}: {e}")
        return []


# --- Original endpoint, now uses the callable function ---
@router.get(
    "/distinct/{field_name}",
    response_model=List[str],
    summary="Get distinct values for a field",
)
async def get_distinct_values_endpoint(
    field_name: ValidField,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a list of all unique, non-null values for a given field
    to populate dropdown menus in the frontend.
    """
    return await get_distinct_values(field_name, db, current_user)


# --- NEW: Consolidated Endpoint (Feature 6) ---
@router.get("/fields", summary="Get all distinct values for all fields")
async def get_all_metadata_fields(
    db: Database = Depends(get_mongo_db), current_user: User = Depends(get_current_user)
):
    """
    Provides a single JSON object with lists of unique values for
    all common frontend dropdown fields.
    """
    fields_to_fetch: List[ValidField] = [
        "District",
        "Police_Station",
        "Court_Name",
        "Investigating_Officer",
        "Rank",
        "Crime_Type",
        "Result",
        "Sections_of_Law",
        "PP_Name",
        "Judge_Name",
    ]

    # Use asyncio.gather to run all queries in parallel
    tasks = [get_distinct_values(field, db, current_user) for field in fields_to_fetch]
    results = await asyncio.gather(*tasks)

    # Zip results with field names
    output = {field: result for field, result in zip(fields_to_fetch, results)}
    return output
