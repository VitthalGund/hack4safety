import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List

from app.db.session import get_pg_session
from app.api.v1.auth import get_current_user
from app.models.user_schema import User, Alert
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()
log = logging.getLogger(__name__)


class AlertOut(BaseModel):
    id: int
    message: str
    read: bool
    link_to: Optional[str]
    timestamp: datetime

    class Config:
        orm_mode = True


@router.get(
    "/feed",
    response_model=List[AlertOut],
    summary="Get the user's 20 most recent alerts",
)
async def get_alert_feed(
    session: AsyncSession = Depends(get_pg_session),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieves the 20 most recent alerts for the currently logged-in user.
    """
    query = (
        select(Alert)
        .where(Alert.user_id == current_user.id)
        .order_by(Alert.timestamp.desc())
        .limit(20)
    )

    result = await session.execute(query)
    alerts = result.scalars().all()
    return alerts


@router.put(
    "/{alert_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark an alert as read",
)
async def mark_alert_as_read(
    alert_id: int,
    session: AsyncSession = Depends(get_pg_session),
    current_user: User = Depends(get_current_user),
):
    """
    Marks a single alert as 'read'.
    """

    # We only update the alert if it belongs to the current user
    query = (
        update(Alert)
        .where(Alert.id == alert_id, Alert.user_id == current_user.id)
        .values(read=True)
    )

    result = await session.execute(query)
    await session.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=404, detail="Alert not found or not owned by user"
        )

    return None
