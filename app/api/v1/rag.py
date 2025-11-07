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


@router.post("/ask", summary="Ask the multilingual legal RAG bot")
async def ask_rag(
    query: RagQuery,
    current_user: User = Depends(get_current_user),  # Protected endpoint
):
    """
    Provides a multilingual, retrieval-augmented answer to a legal query.

    - **Understands:** Most Indian languages (Hindi, Tamil, Telugu, etc.)
    - **Responds:** In the *same language* it was asked.
    - **Grounded:** Answers are based *only* on the ingested legal documents.
    - **Models:** Allows choosing between fast/local (phi-3) or powerful/cloud (gemini).
    """
    if not rag_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG service is not initialized. Check server logs.",
        )

    try:
        response = await rag_service.ask(query.query, query.model_provider)
        return response
    except Exception as e:
        log.error(f"Error in RAG endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))
