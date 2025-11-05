import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from jose import JWTError, jwt
from bcrypt import hashpw, gensalt, checkpw, _bcrypt

from app.models.user_schema import User, UserRole, Base
from app.db.session import get_pg_session, db
from app.core.config import settings
from typing import Optional

router = APIRouter()
log = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None
    role: str | None = None


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: UserRole
    district: Optional[str] = None
    police_station: Optional[str] = None


def verify_password(plain_password: str, hashed_password_str: str) -> bool:
    return checkpw(plain_password.encode("utf-8"), hashed_password_str.encode("utf-8"))


def get_password_hash(password: str) -> str:
    return hashpw(password.encode("utf-8"), gensalt(12)).decode("utf-8")


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


async def create_default_admin():
    """
    Checks for a default admin user on startup and creates one
    if it doesn't exist, using credentials from settings.
    """
    log.info("Checking for default admin user...")

    # Create a new session for this startup task
    async_session_maker = sessionmaker(
        db.pg_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_maker() as session:
        async with session.begin():
            # Check if the specific default admin exists
            result = await session.execute(
                select(User).where(User.username == settings.DEFAULT_ADMIN_USER)
            )
            admin_user = result.scalars().first()

            if admin_user:
                log.info(
                    f"Default admin user '{settings.DEFAULT_ADMIN_USER}' already exists."
                )
                return

            # If no admin exists, create one
            if not settings.DEFAULT_ADMIN_USER or not settings.DEFAULT_ADMIN_PASS:
                log.error(
                    "DEFAULT_ADMIN_USER or DEFAULT_ADMIN_PASS not set. Cannot create default admin."
                )
                return

            log.info(f"Creating default admin user: {settings.DEFAULT_ADMIN_USER}")

            hashed_password = get_password_hash(settings.DEFAULT_ADMIN_PASS)
            default_admin = User(
                username=settings.DEFAULT_ADMIN_USER,
                hashed_password=hashed_password,
                full_name="Default Admin",
                role=UserRole.ADMIN,
                district="STATE_HQ",  # Or any default
            )
            session.add(default_admin)
            await session.commit()
            log.info(
                f"Successfully created default admin user: {settings.DEFAULT_ADMIN_USER}"
            )
        await session.close()


@router.on_event("startup")
async def on_startup():
    """Create all tables (User, Agent) on startup."""
    async with db.pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # After tables are created, create the default admin
    await create_default_admin()


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
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_pg_session),
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


@router.post(
    "/users/create",
    summary="[Admin] Create a new user",
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    user_in: UserCreate,
    session: AsyncSession = Depends(get_pg_session),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new user in the database. Only accessible by ADMIN users.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to create users.",
        )

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

    return {"username": new_user.username, "role": new_user.role, "status": "created"}
