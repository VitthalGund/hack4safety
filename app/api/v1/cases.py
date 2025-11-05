import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from pymongo.database import Database

from app.db.session import get_mongo_db
from app.pqc.secure_server import pqc_server

router = APIRouter()
log = logging.getLogger(__name__)


class SecureWirePackage(BaseModel):
    agent_id: str
    key_id: str
    kem_ciphertext: str
    aes_nonce: str
    encrypted_data_with_tag: str
    signature: str


@router.post("/secure_ingest", summary="Receive a PQC-secured conviction record")
async def secure_ingest_case(
    package: SecureWirePackage, db: Database = Depends(get_mongo_db)
):
    """
    This endpoint is the secure entry point for all agent data.
    It corresponds to the /receive_message route from your original api_server.py
    """
    try:
        message_string, is_verified = pqc_server.process_secure_message(
            package.model_dump()
        )

        if not is_verified:
            log.warning(
                f"Ingestion failed: PQC verification failed for agent {package.agent_id}"
            )
            raise HTTPException(
                status_code=400,
                detail="Failed to decrypt or verify message. Check Key ID, AAD, or signature.",
            )

        try:
            case_data = json.loads(message_string)
        except json.JSONDecodeError:
            log.error(f"Ingestion failed: Decrypted payload was not valid JSON.")
            raise HTTPException(
                status_code=500,
                detail="Data integrity error: Decrypted payload is not valid JSON.",
            )

        # 3. Save the data to MongoDB
        collection = db["conviction_cases"]
        insert_result = await collection.insert_one(case_data)

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
