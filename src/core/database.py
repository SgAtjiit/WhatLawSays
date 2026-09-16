import datetime
from typing import Any, Dict, Optional
from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text
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


class ContractDocumentRecord(Base):
    """An uploaded contract and the review derived from it.

    The extracted text is stored because it is what every offset in the review
    indexes into: without it a stored finding's quote cannot be re-verified, and
    an unverifiable quote is exactly what this pipeline exists to prevent.
    That makes deletion a real requirement rather than a nicety -- contracts
    carry salaries, addresses and party names -- so `delete_contract` removes the
    row outright rather than flagging it.
    """

    __tablename__ = "contract_documents"

    contract_id = Column(String(64), primary_key=True, index=True)
    filename = Column(String(512), nullable=False)
    media_type = Column(String(128), nullable=True)
    contract_type = Column(String(32), nullable=True)
    position = Column(String(32), nullable=True)
    status = Column(String(32), nullable=False, default="QUEUED")
    error = Column(Text, nullable=True)
    document_text = Column(Text, nullable=True)
    char_count = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    clause_count = Column(Integer, nullable=True)
    confidence_score = Column(Float, nullable=True)
    overall_risk = Column(String(16), nullable=True)
    review = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


# When PostgreSQL is unreachable the whole service still runs -- every other
# store in this codebase degrades the same way -- so reviews live here instead.
#
# Used ONLY while PostgreSQL is down. It used to mirror every review, full
# document text included, even with the database healthy: an unbounded store of
# salaries and addresses that never evicted, and that kept serving rows deleted
# from PostgreSQL out of band. PostgreSQL is authoritative whenever it answers;
# this holds at most _MEMORY_LIMIT reviews, oldest evicted first.
_MEMORY_CONTRACTS: Dict[str, Dict[str, Any]] = {}
_MEMORY_LIMIT = 200

# Column widths the model enforces. A value PostgreSQL rejects used to fail the
# whole write silently, so a review with a 600-character filename existed only
# in this process's memory and vanished on restart.
_FILENAME_LIMIT = 512


def _remember(record: Dict[str, Any]) -> None:
    contract_id = record["contract_id"]
    _MEMORY_CONTRACTS[contract_id] = {**_MEMORY_CONTRACTS.get(contract_id, {}), **record}
    while len(_MEMORY_CONTRACTS) > _MEMORY_LIMIT:
        _MEMORY_CONTRACTS.pop(next(iter(_MEMORY_CONTRACTS)))


def _fit(record: Dict[str, Any]) -> Dict[str, Any]:
    fitted = dict(record)
    name = fitted.get("filename")
    if isinstance(name, str) and len(name) > _FILENAME_LIMIT:
        fitted["filename"] = name[: _FILENAME_LIMIT - 1] + "\u2026"
    return fitted


async def _contract_exists(contract_id: str) -> bool:
    try:
        async with AsyncSessionLocal() as session:
            return (await session.get(ContractDocumentRecord, contract_id)) is not None
    except Exception:
        return contract_id in _MEMORY_CONTRACTS


async def save_contract(record: Dict[str, Any], *, update_only: bool = False) -> bool:
    """Insert or update a contract review by contract_id.

    `update_only` writes nothing when the row is gone. A review runs for a
    minute or more, and a user who deletes the contract mid-flight -- salary,
    address, party names -- was told {"deleted": true} and then had the whole
    review re-inserted by the completion write seconds later. Every write that
    follows the initial creation is therefore update-only.
    """
    contract_id = record["contract_id"]
    if update_only and not await _contract_exists(contract_id):
        return False
    record = _fit(record)
    try:
        async with AsyncSessionLocal() as session:
            existing = await session.get(ContractDocumentRecord, contract_id)
            if existing is None:
                session.add(ContractDocumentRecord(**record))
            else:
                for key, value in record.items():
                    setattr(existing, key, value)
                existing.updated_at = datetime.datetime.utcnow()
            await session.commit()
        # PostgreSQL has it; a fallback copy from an earlier outage is stale now.
        _MEMORY_CONTRACTS.pop(contract_id, None)
    except Exception as e:
        _remember(record)
        pipeline_logger.log_step(
            "POSTGRESQL DB",
            f"Contract [{contract_id}] held in the in-memory store "
            f"(PostgreSQL write failed: {type(e).__name__}: {str(e)[:160]})",
            status="WARNING",
        )
    return True


async def get_contract(contract_id: str) -> Optional[Dict[str, Any]]:
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(ContractDocumentRecord, contract_id)
    except Exception:
        # Only an unreachable database falls through to the fallback store. A
        # database that answered "no such row" is believed, so a contract
        # deleted out of band is not served back from memory.
        return _MEMORY_CONTRACTS.get(contract_id)
    if row is None:
        return None
    return {
        column.name: getattr(row, column.name)
        for column in ContractDocumentRecord.__table__.columns
    }


async def delete_contract(contract_id: str) -> bool:
    """Remove a contract and its review from every store.

    A retention promise the product cannot actually keep is worse than no
    promise, so this deletes the row rather than marking it hidden.
    """
    removed = _MEMORY_CONTRACTS.pop(contract_id, None) is not None
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(ContractDocumentRecord, contract_id)
            if row is not None:
                await session.delete(row)
                await session.commit()
                removed = True
    except Exception:
        pass
    return removed


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