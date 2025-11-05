import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.models.user_schema import User, UserRole, Base
from app.db.session import get_pg_session, db
from app.core.config import settings

router = APIRouter()
log = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None
    role: str | None = None


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


@router.on_event("startup")
async def on_startup():
    """Create the User table on startup."""
    async with db.pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@router.post("/token", response_model=Token, summary="User login for JWT token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_pg_session),
):
    """
    Standard OAuth2 password flow to get a JWT token.
    """
    result = await session.execute(
        select(User).where(User.username == form_data.username)
    )
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}


async def get_current_user(
    token: str = Depends(oauth2_scheme), session: AsyncSession = Depends(get_pg_session)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username, role=payload.get("role"))
    except JWTError:
        raise credentials_exception

    result = await session.execute(
        select(User).where(User.username == token_data.username)
    )
    user = result.scalars().first()

    if user is None:
        raise credentials_exception
    return user


@router.get("/users/me", summary="Get current user details")
async def read_users_me(current_user: User = Depends(get_current_user)):
    """
    Protected endpoint that returns the details of the logged-in user.
    """
    return {
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "district": current_user.district,
        "police_station": current_user.police_station,
    }
