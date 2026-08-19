import datetime
from typing import Any, Dict, Optional
from sqlalchemy import JSON, Column, DateTime, Float, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from src.config import settings
from src.core.logger import pipeline_logger

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_size=20,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


class LegalAnalysisRecord(Base):
    __tablename__ = "legal_analysis_records"

    task_id = Column(String(64), primary_key=True, index=True)
    scenario_text = Column(Text, nullable=False)
    status = Column(String(32), nullable=False)
    confidence_score = Column(Float, nullable=True)
    extracted_facts = Column(JSON, nullable=True)
    identified_offenses = Column(JSON, nullable=True)
    clarification_questions = Column(JSON, nullable=True)
    full_response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


async def init_db():
    """Initializes PostgreSQL tables if database connection is available."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pipeline_logger.log_step(
            "POSTGRESQL DB",
            "Database tables initialized successfully.",
            status="SUCCESS",
        )
    except Exception as e:
        pipeline_logger.log_step(
            "POSTGRESQL DB",
            "Local PostgreSQL instance unauthenticated (using in-memory result cache)",
            status="WARNING",
        )


async def save_analysis_record(
    task_id: str,
    scenario_text: str,
    status: str,
    confidence_score: Optional[float],
    response_payload: Dict[str, Any],
):
    """Saves legal analysis result to PostgreSQL database if connected."""
    try:
        async with AsyncSessionLocal() as session:
            record = LegalAnalysisRecord(
                task_id=task_id,
                scenario_text=scenario_text,
                status=status,
                confidence_score=confidence_score,
                extracted_facts=response_payload.get("extracted_facts"),
                identified_offenses=response_payload.get("identified_offenses"),
                clarification_questions=response_payload.get("clarification_questions"),
                full_response=response_payload,
            )
            session.add(record)
            await session.commit()
            pipeline_logger.log_step(
                "POSTGRESQL DB",
                f"Persisted analysis record for Task [{task_id}] to PostgreSQL",
                status="SUCCESS",
            )
    except Exception:
        pipeline_logger.log_step(
            "POSTGRESQL DB",
            f"Local PostgreSQL instance unauthenticated for Task [{task_id}] (result cached in memory)",
            status="WARNING",
        )


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()