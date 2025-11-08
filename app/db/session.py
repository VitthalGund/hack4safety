from pymongo import MongoClient, TEXT, ASCENDING, DESCENDING
from pymongo.database import Database
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
import logging


class DBConnections:
    mongo_client: MongoClient | None = None
    mongo_db = None
    pg_engine = None
    pg_session_local = None


db = DBConnections()


def create_indexes(db_instance: Database):
    """
    Creates necessary indexes on the conviction_cases collection
    to optimize query performance.
    """
    try:
        logging.info("Attempting to create database indexes...")
        cases = db_instance["conviction_cases"]

        # --- Text Index for General Search ---
        cases.create_index(
            [
                ("Case_Number", TEXT),
                ("Accused_Name", TEXT),
                ("Sections_at_Final", TEXT),
                ("FIR_Contents", TEXT),
            ],
            name="text_search_index",
        )

        # --- Indexes for Analytics & Filtering ---
        # For rate calculations and rankings
        cases.create_index(
            [
                ("Result", ASCENDING),
                ("District", ASCENDING),
            ],
            name="idx_rate_district",
        )
        cases.create_index(
            [
                ("Result", ASCENDING),
                ("Court_Name", ASCENDING),
            ],
            name="idx_rate_court",
        )
        cases.create_index(
            [
                ("Result", ASCENDING),
                ("Crime_Type", ASCENDING),
            ],
            name="idx_rate_crime_type",
        )
        cases.create_index(
            [
                ("Result", ASCENDING),
                ("Investigating_Officer", ASCENDING),
            ],
            name="idx_rank_io",
        )
        cases.create_index(
            [
                ("Result", ASCENDING),
                ("Police_Station", ASCENDING),
            ],
            name="idx_rank_ps",
        )
        cases.create_index(
            [
                ("Result", ASCENDING),
                ("Term_Unit", ASCENDING),
            ],
            name="idx_rank_unit",
        )

        # For case duration and trend analysis
        cases.create_index(
            [("Date_of_Judgement", DESCENDING)], name="idx_trends_judgement_date"
        )
        cases.create_index(
            ["Date_of_Registration", "Date_of_Chargesheet", "Date_of_Judgement"],
            name="idx_duration_kpi",
        )

        # --- Index for Case List Pagination ---
        cases.create_index(
            [("Date_of_Registration", DESCENDING)], name="idx_case_list_sort"
        )

        # Index for personnel scorecard
        cases.create_index(
            [("Investigating_Officer", ASCENDING), ("Date_of_Judgement", DESCENDING)],
            name="idx_personnel_scorecard",
        )

        logging.info("Database indexes created successfully.")
    except Exception as e:
        logging.error(f"Failed to create indexes: {e}")


def connect_to_mongo():
    """Establishes connection to MongoDB."""
    logging.info("Connecting to MongoDB...")
    try:
        db.mongo_client = MongoClient(settings.MONGO_URL)
        db.mongo_db = db.mongo_client[settings.MONGO_DB_NAME]
        # Ping the server to confirm connection
        db.mongo_client.server_info()
        logging.info("Successfully connected to MongoDB.")

        # --- ADDED: Call index creation after connection ---
        create_indexes(db.mongo_db)

    except Exception as e:
        logging.error(f"Failed to connect to MongoDB: {e}")
        raise


def close_mongo_connection():
    """Closes MongoDB connection."""
    logging.info("Closing MongoDB connection...")
    if db.mongo_client:
        db.mongo_client.close()
    logging.info("MongoDB connection closed.")


def connect_to_postgres():
    """Establishes connection to PostgreSQL."""
    logging.info("Connecting to PostgreSQL...")
    try:
        db.pg_engine = create_async_engine(
            settings.POSTGRES_URL,
            pool_pre_ping=True,
            echo=False,
            # Removed "ssl": "require" as it can cause issues
            # connect_args={"ssl": "require"},
        )
        db.pg_session_local = sessionmaker(
            bind=db.pg_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        logging.info("Successfully connected to PostgreSQL engine.")
    except Exception as e:
        logging.error(f"Failed to connect to PostgreSQL: {e}")
        raise


async def close_postgres_connection():
    """Closes PostgreSQL connection."""
    logging.info("Closing PostgreSQL connection...")
    if db.pg_engine:
        await db.pg_engine.dispose()
    logging.info("PostgreSQL connection closed.")


async def get_pg_session() -> AsyncSession:
    """Dependency to get a new PostgreSQL session."""
    if not db.pg_session_local:
        raise Exception("PostgreSQL session not initialized.")

    async with db.pg_session_local() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_mongo_db():
    """Dependency to get the MongoDB database instance."""
    if db.mongo_db is None:
        raise Exception("MongoDB connection not initialized.")
    return db.mongo_db
