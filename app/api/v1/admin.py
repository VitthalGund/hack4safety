import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.db.session import get_pg_session, get_mongo_db
from app.api.v1.auth import get_current_user, get_password_hash
from app.models.user_schema import User, UserRole, UserOut, UserUpdate, UserCreate
from pymongo.database import Database

log = logging.getLogger(__name__)


# --- Admin-only Dependency ---
async def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized. Admin access required.",
        )
    return current_user


router = APIRouter(dependencies=[Depends(get_admin_user)])

# --- User Management Endpoints (Feature 1) ---


@router.get("/users", response_model=List[UserOut], summary="List all users")
async def list_users(session: AsyncSession = Depends(get_pg_session)):
    """
    Get a list of all registered users in the system.
    """
    result = await session.execute(select(User))
    users = result.scalars().all()
    return users


@router.post(
    "/users",
    response_model=UserOut,
    summary="Create a new user",
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    user_in: UserCreate, session: AsyncSession = Depends(get_pg_session)
):
    """
    Create a new user in the database. (Moved from auth.py)
    """
    result = await session.execute(
        select(User).where(User.username == user_in.username)
    )
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    hashed_password = get_password_hash(user_in.password)
    new_user = User(
        username=user_in.username,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
        role=user_in.role,
        district=user_in.district,
        police_station=user_in.police_station,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    return new_user


@router.put(
    "/users/{user_id}", response_model=UserOut, summary="Update a user's details"
)
async def update_user(
    user_id: int, user_in: UserUpdate, session: AsyncSession = Depends(get_pg_session)
):
    """
    Update a user's role, name, district, or police station.
    """
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    update_data = user_in.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)

    session.add(user)
    await session.commit()
    await session.refresh(user)

    return user


# --- Data Quality Endpoint (Feature 1) ---


@router.get("/data-quality-report", summary="Get data quality anomaly report")
async def get_data_quality_report(db: Database = Depends(get_mongo_db)):
    """
    Runs aggregation pipelines to find potential data quality issues.
    """

    # 1. Missing Judgement Date
    missing_judgement_query = {
        "Result": {"$in": ["Conviction", "Acquitted"]},
        "$or": [{"Date_of_Judgement": None}, {"Date_of_Judgement": ""}],
    }
    missing_judgement_count = db["conviction_cases"].count_documents(
        missing_judgement_query
    )

    # 2. Invalid Date Logic (Judgement before Chargesheet)
    invalid_dates_pipeline = [
        {
            "$project": {
                "Case_Number": 1,
                "Date_of_Judgement": {"$toDate": "$Date_of_Judgement"},
                "Date_of_Chargesheet": {"$toDate": "$Date_of_Chargesheet"},
            }
        },
        {"$match": {"Date_of_Judgement": {"$lt": "$Date_of_Chargesheet"}}},
        {"$count": "count"},
    ]
    invalid_dates_result = list(
        db["conviction_cases"].aggregate(invalid_dates_pipeline)
    )
    invalid_dates_count = (
        invalid_dates_result[0]["count"] if invalid_dates_result else 0
    )

    return {
        "anomalies_found": {
            "missing_judgement_date_count": missing_judgement_count,
            "judgement_before_chargesheet_count": invalid_dates_count,
        }
    }
