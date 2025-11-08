import json
import logging
from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel, Field
from pymongo.database import Database
from typing import Dict, Any, List, Optional
from bson import ObjectId
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.db.session import get_mongo_db, get_pg_session
from app.pqc.secure_server import server_core as pqc_server
from app.api.v1.auth import get_current_user
from app.models.user_schema import (
    User,
    UserRole,
    Agent,
    Alert,
)  # Added UserRole, Agent, Alert
from app.core.embedding import embeddings_client

router = APIRouter()
log = logging.getLogger(__name__)


# --- Helper Function for Case RAG ---
# ... (This function is unchanged from the previous step)
def _create_case_embedding(case_data: dict) -> List[float]:
    if not embeddings_client:
        log.error("Embedding client not loaded. Cannot create case embedding.")
        return []
    text_to_embed = f"""
    Case Number: {case_data.get('Case_Number', '')}
    District: {case_data.get('District', '')}
    Police Station: {case_data.get('Police_Station', '')}
    Accused: {case_data.get('Accused_Details', '')}
    Crime: {case_data.get('Crime_Type', '')}
    Sections: {case_data.get('Sections_of_Law', '')}
    FIR Contents: {case_data.get('FIR_Contents', '')}
    Action Taken: {case_data.get('Action_Taken', '')}
    Result: {case_data.get('Result', '')}
    """
    embedding = embeddings_client.embed_query(text_to_embed)
    return embedding


# ... (SecureWirePackage, CaseOut, CaseFieldUpdate models are unchanged) ...
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
        orm_mode = True


class CaseFieldUpdate(BaseModel):
    field_name: str = Field(..., description="The exact name of the field to update.")
    field_value: Any = Field(..., description="The new value for the field.")


# --- NEW: Pydantic models for Feature 2 ---
class DocumentOut(BaseModel):
    case_mongo_id: str
    document_type: str
    name: str
    storage_url: str
    uploaded_at: str


class GlobalSearchResult(BaseModel):
    type: str
    id: str
    name: str
    context: str


# --- Endpoints ---


@router.post("/secure_ingest", summary="Receive a PQC-secured conviction record")
async def secure_ingest_case(
    package: SecureWirePackage,
    db: Database = Depends(get_mongo_db),
    pg_session: AsyncSession = Depends(get_pg_session),
):
    """
    This endpoint is the secure entry point for all agent data.
    It fetches the agent's key, verifies the payload,
    EMBEDS the content, and saves to MongoDB.
    """
    if not embeddings_client:
        raise HTTPException(
            status_code=503, detail="Embedding service is not available."
        )
    try:
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
        result = pqc_server.process_secure_message(
            package.model_dump(), agent.dilithium_pk
        )
        if result.get("status") != "ok":
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

        # 3. Create Embedding
        case_data["case_embedding"] = _create_case_embedding(case_data)

        # 4. Save to MongoDB
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


# --- NEW: Global Search Endpoint (Feature 2) ---
@router.get(
    "/search/global",
    response_model=List[GlobalSearchResult],
    summary="Global federated search",
)
async def search_global(
    q: str = Query(..., min_length=3, description="Global search query"),
    db: Database = Depends(get_mongo_db),
    pg_session: AsyncSession = Depends(get_pg_session),
    current_user: User = Depends(get_current_user),
):
    """
    Performs a federated search across cases, personnel, and accused.
    """
    results: List[GlobalSearchResult] = []

    # 1. Search Cases (MongoDB Text Search)
    case_query = {"$text": {"$search": q}}
    # Apply role-based filtering
    if current_user.role == UserRole.SP:
        case_query["District"] = current_user.district
    elif current_user.role == UserRole.IIC:
        case_query["Police_Station"] = current_user.police_station

    case_cursor = (
        db["conviction_cases"]
        .find(case_query, {"Case_Number": 1, "District": 1, "Police_Station": 1})
        .limit(5)
    )

    for case in case_cursor:
        results.append(
            GlobalSearchResult(
                type="Case",
                id=str(case["_id"]),
                name=case["Case_Number"],
                context=f"{case.get('District', '')} / {case.get('Police_Station', '')}",
            )
        )

    # 2. Search Personnel (Postgres)
    personnel_query = (
        select(User)
        .where(
            User.full_name.ilike(f"%{q}%"),
            User.role.in_(
                [UserRole.IIC, UserRole.SP, UserRole.SDPO]
            ),  # Only search for officers
        )
        .limit(5)
    )

    pg_result = await pg_session.execute(personnel_query)
    for user in pg_result.scalars().all():
        results.append(
            GlobalSearchResult(
                type="Personnel",
                id=str(user.id),
                name=user.full_name,
                context=f"{user.role.value} / {user.district or user.police_station}",
            )
        )

    # 3. Search Accused (MongoDB Distinct)
    accused_query = {"Accused_Name": {"$regex": q, "$options": "i"}}
    if current_user.role == UserRole.SP:
        accused_query["District"] = current_user.district
    elif current_user.role == UserRole.IIC:
        accused_query["Police_Station"] = current_user.police_station

    accused_names = db["conviction_cases"].distinct("Accused_Name", accused_query)

    for name in accused_names[:5]:  # Limit to 5
        results.append(
            GlobalSearchResult(
                type="Accused", id=name, name=name, context="Accused Person"
            )
        )

    return results


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

    # Role-based filtering
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
    cases_cursor = collection.find(query, {"case_embedding": 0}).limit(
        limit
    )  # Exclude embedding
    results = []
    for case in cases_cursor:
        case["_id"] = str(case["_id"])
        results.append(case)
    return results


@router.get("/{case_mongo_id}", summary="Get a single full case by its MongoDB ID")
async def get_full_case(
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
    # Role-based access check
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


@router.put("/{case_mongo_id}/field", summary="Update a field in a case document")
async def update_case_field(
    case_mongo_id: str,
    update_data: CaseFieldUpdate,
    db: Database = Depends(get_mongo_db),
    pg_session: AsyncSession = Depends(get_pg_session),  # <-- ADDED
    current_user: User = Depends(get_current_user),
):
    """
    Updates a single field in a case document.
    If a RAG-related field is updated, this regenerates the case embedding.
    If 'Result' is updated, this triggers an Alert (Feature 7).
    """
    if not embeddings_client:
        raise HTTPException(
            status_code=503, detail="Embedding service is not available."
        )
    try:
        obj_id = ObjectId(case_mongo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid MongoDB ID format")

    collection = db["conviction_cases"]

    # 1. Get the case
    case = collection.find_one({"_id": obj_id})
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    # 2. Check permissions
    if (
        current_user.role == UserRole.SP
        and case.get("District") != current_user.district
    ) or (
        current_user.role == UserRole.IIC
        and case.get("Police_Station") != current_user.police_station
    ):
        if current_user.role not in [UserRole.ADMIN]:  # Only Admin can bypass
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
            )

    # 3. Set the new field value
    update_payload = {"$set": {update_data.field_name: update_data.field_value}}
    case[update_data.field_name] = update_data.field_value  # Update in-memory copy

    # 4. Check if we need to update the embedding
    rag_fields = [
        "FIR_Contents",
        "Action_Taken",
        "Accused_Details",
        "Crime_Type",
        "Sections_of_Law",
        "Result",
    ]
    if update_data.field_name in rag_fields:
        log.info(
            f"RAG field updated. Regenerating embedding for case {case_mongo_id}..."
        )
        new_embedding = _create_case_embedding(case)
        update_payload["$set"]["case_embedding"] = new_embedding

    # 5. Perform the update
    result = collection.update_one({"_id": obj_id}, update_payload)

    # 6. --- NEW: Alert Trigger (Feature 7) ---
    if update_data.field_name == "Result" and update_data.field_value in [
        "Conviction",
        "Acquitted",
    ]:
        await create_alert_for_case_update(
            pg_session, case, update_data.field_value, str(obj_id)
        )

    return {"status": "updated", "modified_count": result.modified_count}


# --- NEW: Document Endpoint (Feature 2) ---
@router.get(
    "/{case_mongo_id}/documents",
    response_model=List[DocumentOut],
    summary="Get documents for a single case",
)
async def get_case_documents(
    case_mongo_id: str,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieves a list of all associated documents (like FIRs, Chargesheets)
    for a single case.
    """
    # Note: We must also check if the user has access to the *case* itself.
    # We can re-use the get_full_case logic.
    await get_full_case(case_mongo_id, db, current_user)

    # Logic assumes a new collection "case_documents"
    collection = db["case_documents"]
    documents = list(collection.find({"case_mongo_id": case_mongo_id}))

    # Convert _id
    for doc in documents:
        doc["id"] = str(doc["_id"])

    return documents


# --- NEW: Helper for Alert Trigger (Feature 7) ---
async def create_alert_for_case_update(
    pg_session: AsyncSession, case: dict, new_result: str, case_mongo_id: str
):
    """
    Finds relevant users (IO, SP) and creates a new Alert in Postgres.
    """
    try:
        io_name = case.get("Investigating_Officer")
        district = case.get("District")
        case_number = case.get("Case_Number")

        # Find users who are either the IO for this case OR the SP for this district
        user_query = select(User).where(
            or_(
                User.full_name == io_name,
                (User.role == UserRole.SP and User.district == district),
            )
        )
        users_to_alert = (await pg_session.execute(user_query)).scalars().all()

        if not users_to_alert:
            log.warning(f"No users found to alert for case {case_number}")
            return

        alerts = []
        for user in users_to_alert:
            new_alert = Alert(
                user_id=user.id,
                message=f"Case {case_number} has been updated. New result: {new_result}",
                link_to=f"/app/cases/{case_mongo_id}",  # Frontend link
            )
            alerts.append(new_alert)

        pg_session.add_all(alerts)
        await pg_session.commit()
        log.info(f"Created {len(alerts)} alerts for case {case_number} update.")

    except Exception as e:
        log.error(f"Failed to create alert: {e}")
        await pg_session.rollback()


# ... (delete_case endpoint is unchanged) ...
@router.delete("/{case_mongo_id}", summary="Delete a case document")
async def delete_case(
    case_mongo_id: str,
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deletes a case document. (Primarily for Admin/SP roles).
    """
    try:
        obj_id = ObjectId(case_mongo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid MongoDB ID format")

    collection = db["conviction_cases"]

    # 1. Get the case to check permissions
    case = collection.find_one({"_id": obj_id})
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    # 2. Check permissions
    if (
        current_user.role == UserRole.SP
        and case.get("District") != current_user.district
    ) or (
        current_user.role == UserRole.IIC
        and case.get("Police_Station") != current_user.police_station
    ):
        # Only SP, IIC, or Admin can delete. IIC/SP only in their jurisdiction.
        if current_user.role not in [UserRole.ADMIN, UserRole.SP, UserRole.IIC]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
            )

    # 3. Perform delete
    result = collection.delete_one({"_id": obj_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Case not found during deletion.")

    return {"status": "deleted", "deleted_count": result.deleted_count}
