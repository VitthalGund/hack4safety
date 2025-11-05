from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.pqc.secure_server import pqc_server  # Import our singleton

router = APIRouter()


def convert_bytes_to_hex(data: bytes) -> str:
    """Converts bytes to a hex string."""
    return data.hex()


class AgentRegistration(BaseModel):
    agent_id: str
    dilithium_pk_hex: str


# --- API Endpoints (Migrated from your api_server.py) ---


@router.get("/setup", summary="Get Server PQC Public Key")
async def setup():
    """
    Endpoint for a Secure Agent to retrieve the server's current Kyber Public Key.
    """
    try:
        server_pk, key_id = pqc_server.get_server_public_key()
        response = {
            "server_public_key": convert_bytes_to_hex(server_pk),
            "key_id": key_id,
        }
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.post("/register_agent", summary="Register an Agent's PQC Public Key")
async def register_agent(agent_data: AgentRegistration):
    """
    Endpoint for a Secure Agent to register its Dilithium Public Key.
    """
    if pqc_server.register_agent(agent_data.agent_id, agent_data.dilithium_pk_hex):
        return {
            "status": "Agent registered successfully",
            "agent_id": agent_data.agent_id,
        }
    else:
        raise HTTPException(
            status_code=400, detail="Failed to register agent (e.g., bad hex format)."
        )


@router.post("/rotate_keys", summary="[Admin] Trigger Server Key Rotation")
async def rotate_keys():
    """
    Triggers a manual key rotation for the server's Kyber keys.
    (TODO: This should be protected by an admin auth route)
    """
    try:
        new_pk, new_id = pqc_server.rotate_keys()
        return {
            "status": "Key rotation successful",
            "new_key_id": new_id,
            "new_pk_fingerprint": convert_bytes_to_hex(new_pk[:16]) + "...",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.get("/status", summary="Get Server Health and PQC Status")
async def get_status():
    """
    Provides a security health check and operational metrics.
    """
    audit_summary = {
        "total_verified_messages": sum(
            1 for log in pqc_server.audit_log if log["verified"]
        ),
        "total_failed_verification": sum(
            1 for log in pqc_server.audit_log if not log["verified"]
        ),
        "last_key_rotation_id": pqc_server.key_id,
        "number_of_registered_agents": len(pqc_server.registered_agents),
    }

    pk_fingerprint = convert_bytes_to_hex(pqc_server.server_pk[:16]) + "..."

    return {
        "system_status": "Operational: Quantum-Safe Secure",
        "key_management": {
            "current_key_id": pqc_server.key_id,
            "kyber_pk_fingerprint": pk_fingerprint,
            "registered_agents": list(pqc_server.registered_agents.keys()),
        },
        "security_audit_summary": audit_summary,
    }
