import json
import logging
from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel, Field
from pymongo.database import Database
from typing import Dict, Any, List, Optional
from bson import ObjectId
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_mongo_db, get_pg_session
from app.pqc.secure_server import server_core as pqc_server
from app.api.v1.auth import get_current_user
from app.models.user_schema import User, UserRole, Agent  # Added UserRole, Agent

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
    package: SecureWirePackage,
    db: Database = Depends(get_mongo_db),
    pg_session: AsyncSession = Depends(get_pg_session),  # <-- ADDED
):
    """
    This endpoint is the secure entry point for all agent data.
    It fetches the agent's key from Postgres, then verifies the payload.
    """
    try:
        # --- TODO 3 IMPLEMENTED (Part 2) ---
        # 1. Fetch agent's public key from PostgreSQL
        result = await pg_session.execute(
            select(Agent).where(Agent.agent_id == package.agent_id)
        )
        agent = result.scalars().first()

        if not agent:
            log.warning(
                f"Ingestion failed: Agent ID '{package.agent_id}' not registered."
            )
            raise HTTPException(
                status_code=401,
                detail=f"Agent ID '{package.agent_id}' is not registered.",
            )

        agent_pk_bytes = agent.dilithium_pk

        # 2. Process the package using the fetched key
        result = pqc_server.process_secure_message(package.model_dump(), agent_pk_bytes)

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
    current_user: User = Depends(get_current_user),
    sections_of_law: Optional[str] = Query(None),
    accused_name: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    court_name: Optional[str] = Query(None),
    investigating_officer: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Implements the 'Filter & Search Capabilities'.
    This endpoint is protected and requires a valid JWT token.
    Access is restricted based on the user's role.
    """
    query: Dict[str, Any] = {}

    if sections_of_law:
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

    # --- TODO 1 IMPLEMENTED ---
    # Apply role-based filtering
    if current_user.role == UserRole.SP:
        # SP can only see cases in their assigned District
        if district and district != current_user.district:
            # If they try to search for another district, return empty
            return []
        query["District"] = current_user.district

    elif current_user.role == UserRole.IIC:
        # IIC can only see cases in their assigned Police Station
        query["Police_Station"] = current_user.police_station

    # ADMIN, SDPO, and COURT_LIAISON can see all (in this logic)

    log.info(
        f"User '{current_user.username}' (Role: {current_user.role}) searching with query: {query}"
    )

    collection = db["conviction_cases"]
    cases_cursor = collection.find(query).limit(limit)

    results = []
    for case in cases_cursor:
        case["_id"] = str(case["_id"])
        results.append(case)

    return results


@router.get("/{case_mongo_id}", summary="Get a single case by its MongoDB ID")
async def get_case_by_id(
    case_mongo_id: str,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieves the full details for a single case.
    Access is restricted based on the user's role.
    """
    try:
        obj_id = ObjectId(case_mongo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid MongoDB ID format")

    collection = db["conviction_cases"]
    case = collection.find_one({"_id": obj_id})

    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    # --- TODO 2 IMPLEMENTED ---
    # Check role-based access
    if current_user.role == UserRole.SP:
        if case.get("District") != current_user.district:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Case is not in your district.",
            )

    elif current_user.role == UserRole.IIC:
        if case.get("Police_Station") != current_user.police_station:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Case is not in your police station.",
            )

    case["_id"] = str(case["_id"])
    return case
