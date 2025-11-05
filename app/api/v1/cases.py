import json
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from pymongo.database import Database
from typing import Dict, Any, List, Optional
from bson import ObjectId

from app.db.session import get_mongo_db

from app.pqc.secure_server import server_core as pqc_server

from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)


class SecureWirePackage(BaseModel):
    agent_id: str
    key_id: int
    kem_ciphertext: str
    nonce: str
    ciphertext: str
    signature: str
    aad: Dict[str, Any]


class CaseOut(BaseModel):
    id: str = Field(..., alias="_id")
    Case_Number: str
    Police_Station: str
    District: str
    Investigating_Officer: str
    Accused_Name: str
    Sections_of_Law: str
    Result: str

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}


@router.post("/secure_ingest", summary="Receive a PQC-secured conviction record")
async def secure_ingest_case(
    package: SecureWirePackage, db: Database = Depends(get_mongo_db)
):
    """
    This endpoint is the secure entry point for all agent data.
    It corresponds to the /receive_message route.
    """
    try:
        result = pqc_server.process_secure_message(package.model_dump())

        if result.get("status") != "ok":
            log.warning(f"Ingestion failed: {result.get('error')}")
            raise HTTPException(
                status_code=400, detail=f"PQC processing failed: {result.get('error')}"
            )

        try:
            case_data = json.loads(result["plaintext"])
        except json.JSONDecodeError:
            log.error(f"Ingestion failed: Decrypted payload was not valid JSON.")
            raise HTTPException(
                status_code=500,
                detail="Data integrity error: Decrypted payload is not valid JSON.",
            )

        # 3. Save the data to MongoDB
        collection = db["conviction_cases"]
        insert_result = collection.insert_one(case_data)

        log.info(
            f"Successfully ingested case {case_data.get('Case_Number')} from agent {package.agent_id}"
        )

        return {
            "status": "Message processed and verified successfully",
            "case_number": case_data.get("Case_Number"),
            "mongo_id": str(insert_result.inserted_id),
        }

    except Exception as e:
        log.error(f"Error in secure_ingest endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/search",
    response_model=List[CaseOut],
    summary="Search and filter conviction cases",
)
async def search_cases(
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(
        get_current_user
    ),  # <-- This endpoint is now protected
    # --- Filter parameters from PS ---
    sections_of_law: Optional[str] = Query(
        None, description="Filter by Sections of Law (e.g., IPC 323)"
    ),
    accused_name: Optional[str] = Query(None, description="Filter by Accused Name"),
    district: Optional[str] = Query(None, description="Filter by District"),
    court_name: Optional[str] = Query(None, description="Filter by Court Name"),
    investigating_officer: Optional[str] = Query(
        None, description="Filter by Investigating Officer"
    ),
    result: Optional[str] = Query(
        None, description="Filter by Result (e.g., Acquitted, Conviction)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Number of results to return"),
):
    """
    Implements the 'Filter & Search Capabilities'.
    This endpoint is protected and requires a valid JWT token.
    """
    query: Dict[str, Any] = {}

    # Build the MongoDB query dynamically
    if sections_of_law:
        # Use regex for partial matching
        query["Sections_of_Law"] = {"$regex": sections_of_law, "$options": "i"}
    if accused_name:
        query["Accused_Name"] = {"$regex": accused_name, "$options": "i"}
    if district:
        query["District"] = district
    if court_name:
        query["Court_Name"] = court_name
    if investigating_officer:
        query["Investigating_Officer"] = {
            "$regex": investigating_officer,
            "$options": "i",
        }
    if result:
        query["Result"] = result

    # TODO: Add role-based filtering
    # if current_user.role == UserRole.SP:
    #     query["District"] = current_user.district
    # if current_user.role == UserRole.IIC:
    #     query["Police_Station"] = current_user.police_station

    log.info(f"User '{current_user.username}' searching with query: {query}")

    # Find the data
    collection = db["conviction_cases"]
    cases_cursor = collection.find(query).limit(limit)

    # Convert cursor to list and handle BSON _id
    results = []
    for case in cases_cursor:
        case["_id"] = str(case["_id"])  # Convert ObjectId to string
        results.append(case)

    return results


@router.get("/{case_mongo_id}", summary="Get a single case by its MongoDB ID")
async def get_case_by_id(
    case_mongo_id: str,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),  # <-- Also protected
):
    """
    Retrieves the full details for a single case.
    """
    try:
        obj_id = ObjectId(case_mongo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid MongoDB ID format")

    collection = db["conviction_cases"]
    case = collection.find_one({"_id": obj_id})

    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    # TODO: Add role-based access check here

    case["_id"] = str(case["_id"])
    return case
