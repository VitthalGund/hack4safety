from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.pqc.secure_server import server_core as pqc_server

from app.db.session import get_pg_session
from app.models.user_schema import Agent, User, UserRole
from app.api.v1.auth import get_current_user

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
        response = pqc_server.get_server_public_key()
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.post("/register_agent", summary="Register an Agent's PQC Public Key")
async def register_agent(
    agent_data: AgentRegistration,
    session: AsyncSession = Depends(get_pg_session),
    # TODO: This should be protected by an admin route too
):
    """
    Endpoint for a Secure Agent to register its Dilithium Public Key.
    Saves the agent's key to the PostgreSQL database.
    """
    try:
        # Check if agent already exists
        result = await session.execute(
            select(Agent).where(Agent.agent_id == agent_data.agent_id)
        )
        existing_agent = result.scalars().first()

        pk_bytes = bytes.fromhex(agent_data.dilithium_pk_hex)

        if existing_agent:
            # Update existing agent's key
            existing_agent.dilithium_pk = pk_bytes
        else:
            # Create new agent
            new_agent = Agent(agent_id=agent_data.agent_id, dilithium_pk=pk_bytes)
            session.add(new_agent)

        await session.commit()

        return {
            "status": "Agent registered successfully",
            "agent_id": agent_data.agent_id,
        }
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid hex format for public key."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register agent: {e}")


@router.post("/rotate_keys", summary="[Admin] Trigger Server Key Rotation")
async def rotate_keys(
    current_user: User = Depends(get_current_user),  # <-- ADDED SECURITY
):
    """
    Triggers a manual key rotation for the server's Kyber keys.
    Only accessible by users with the ADMIN role.
    """
    # --- TODO 4 IMPLEMENTED ---
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )

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
async def get_status(session: AsyncSession = Depends(get_pg_session)):  # Added session
    """
    Provides a security health check and operational metrics.
    """
    # Get agent count from the database
    result = await session.execute(select(Agent))
    agent_count = len(result.scalars().all())

    return {
        "system_status": "Operational: Quantum-Safe Secure",
        "key_management": {
            "current_key_id": pqc_server.key_id,
            "kem_algorithm": pqc_server.kem_alg,
            "registered_agents_count": agent_count,
        },
    }
