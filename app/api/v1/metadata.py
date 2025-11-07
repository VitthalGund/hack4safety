import logging
from fastapi import APIRouter, Depends
from pymongo.database import Database
from typing import List, Literal

from app.db.session import get_mongo_db
from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)

ValidField = Literal[
    "District",
    "Police_Station",
    "Court_Name",
    "Investigating_Officer",
    "Rank",
    "Crime_Type",
    "Result",
]


@router.get(
    "/distinct/{field_name}",
    response_model=List[str],
    summary="Get distinct values for a field",
)
async def get_distinct_values(
    field_name: ValidField,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a list of all unique, non-null values for a given field
    to populate dropdown menus in the frontend.
    """
    try:
        collection = db["conviction_cases"]
        values = collection.distinct(field_name)

        results = [val for val in values if val]
        results.sort()
        print(results)
        return results
    except Exception as e:
        log.error(f"Failed to get distinct values for {field_name}: {e}")
        return []
