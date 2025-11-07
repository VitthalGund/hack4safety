import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Literal

from app.api.v1.auth import get_current_user
from app.models.user_schema import User

# Import our new service
from app.services.rag_service import rag_service

router = APIRouter()
log = logging.getLogger(__name__)


class RagQuery(BaseModel):
    query: str = Field(..., description="User's query in any Indian language.")
    model_provider: Literal["gemini", "phi-3"] = Field(
        "gemini", description="The LLM to use. 'gemini' for cloud, 'phi-3' for local."
    )


@router.post("/legal", summary="Ask the legal bot (Indian Laws)")
async def ask_legal_rag(
    query: RagQuery, current_user: User = Depends(get_current_user)  # Protected
):
    """
    RAG bot for general Indian legal questions.
    Grounded in the `legal_vectors` collection (IPC, BNS, etc.).
    """
    if not rag_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG service is not initialized. Check server logs.",
        )
    try:
        response = await rag_service.ask_legal_bot(query.query, query.model_provider)
        return response
    except Exception as e:
        log.error(f"Error in legal RAG endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases", summary="Ask questions about your conviction cases")
async def ask_cases_rag(
    query: RagQuery, current_user: User = Depends(get_current_user)  # Protected
):
    """
    RAG bot for your internal conviction case data.
    Grounded in the `conviction_cases` collection (FIRs, Actions Taken, etc.).
    """
    if not rag_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG service is not initialized. Check server logs.",
        )
    try:
        response = await rag_service.ask_case_bot(query.query, query.model_provider)
        return response
    except Exception as e:
        log.error(f"Error in cases RAG endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))
