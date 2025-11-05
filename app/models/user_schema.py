from sqlalchemy import Column, String, Integer, Enum as SQLEnum, LargeBinary
from sqlalchemy.orm import declarative_base
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
    role = Column(SQLEnum(UserRole), nullable=False)
    district = Column(String, index=True, nullable=True)  # For SP/SDPO
    police_station = Column(String, index=True, nullable=True)  # For IIC


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, unique=True, index=True, nullable=False)
    dilithium_pk = Column(LargeBinary, nullable=False)
