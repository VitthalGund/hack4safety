from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.pqc.secure_server import server_core as pqc_server

router = APIRouter()


class AgentRegistration(BaseModel):
    agent_id: str
    dilithium_pk_hex: str


@router.get("/setup", summary="Get Server PQC Public Key")
async def setup():
    """
    Endpoint for a Secure Agent to retrieve the server's current Kyber Public Key.
    """
    try:
        # The new get_server_public_key() returns a dict, which is fine.
        response = pqc_server.get_server_public_key()
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.post("/register_agent", summary="Register an Agent's PQC Public Key")
async def register_agent(agent_data: AgentRegistration):
    """
    Endpoint for a Secure Agent to register its Dilithium Public Key.
    """
    try:
        pqc_server.register_agent(agent_data.agent_id, agent_data.dilithium_pk_hex)
        return {
            "status": "Agent registered successfully",
            "agent_id": agent_data.agent_id,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to register agent: {e}")


@router.post("/rotate_keys", summary="[Admin] Trigger Server Key Rotation")
async def rotate_keys():
    """
    Triggers a manual key rotation for the server's Kyber keys.
    (TODO: This should be protected by an admin auth route)
    """
    try:
        new_key_info = pqc_server.rotate_keys()
        return {
            "status": "Key rotation successful",
            "new_key_id": new_key_info["key_id"],
            "new_pk_fingerprint": new_key_info["server_public_key"][:40] + "...",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.get("/status", summary="Get Server Health and PQC Status")
async def get_status():
    """
    Provides a security health check and operational metrics.
    """
    return {
        "system_status": "Operational: Quantum-Safe Secure",
        "key_management": {
            "current_key_id": pqc_server.key_id,
            "kem_algorithm": pqc_server.kem_alg,
            "registered_agents": list(pqc_server.agent_pubkeys.keys()),
        },
    }
