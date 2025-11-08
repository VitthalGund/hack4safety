from sqlalchemy import (
    Column,
    String,
    Integer,
    Enum as SQLEnum,
    LargeBinary,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
from pydantic import BaseModel
from typing import Optional
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    IIC = "IIC"
    SDPO = "SDPO"
    SP = "SP"
    COURT_LIAISON = "COURT_LIAISON"
    ADMIN = "ADMIN"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.COURT_LIAISON)
    district = Column(String, index=True, nullable=True)  # For SP/SDPO
    police_station = Column(String, index=True, nullable=True)  # For IIC


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, unique=True, index=True, nullable=False)
    dilithium_pk = Column(LargeBinary, nullable=False)


# --- NEW: As per Feature 7 ---
class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(String, nullable=False)
    read = Column(Boolean, default=False)
    link_to = Column(String, nullable=True)  # e.g., /app/cases/{case_id}
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


# --- NEW: Pydantic schemas for Admin module (Feature 1) ---


class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
    role: UserRole
    district: Optional[str]
    police_station: Optional[str]

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    district: Optional[str] = None
    police_station: Optional[str] = None


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: UserRole
    district: Optional[str] = None
    police_station: Optional[str] = None
