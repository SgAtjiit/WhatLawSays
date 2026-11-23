"""Saved Legal companion conversations.

PostgreSQL when it answers; otherwise a bounded in-memory store, the same way
contract reviews degrade (see `database.py`). Ownership is checked by the
caller: every function here takes ids, not users.
"""

import datetime
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select

from src.core.database import AsyncSessionLocal, ConversationMessageRecord, ConversationRecord
from src.core.logger import pipeline_logger

_MEMORY: Dict[str, Dict[str, Any]] = {}
_MEMORY_LIMIT = 200
TITLE_LIMIT = 200

_CONVERSATION_FIELDS = ("conversation_id", "owner_uid", "title", "created_at", "updated_at")
_MESSAGE_FIELDS = ("message_id", "role", "content", "sources", "cited", "degraded", "created_at")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _iso(value):
    return value.isoformat() + "Z" if isinstance(value, datetime.datetime) else value


def _conversation(row: Dict[str, Any]) -> Dict[str, Any]:
    return {field: _iso(row.get(field)) for field in _CONVERSATION_FIELDS}


def _message(row: Dict[str, Any]) -> Dict[str, Any]:
    message = {field: _iso(row.get(field)) for field in _MESSAGE_FIELDS}
    message["sources"] = message["sources"] or []
    message["cited"] = message["cited"] or []
    message["degraded"] = bool(message["degraded"])
    return message


def _columns(record_class, row) -> Dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in record_class.__table__.columns}


def _warn(action: str, error: Exception) -> None:
    pipeline_logger.log_step(
        "POSTGRESQL DB",
        f"Conversation {action} held in memory (PostgreSQL: {type(error).__name__}: {str(error)[:160]})",
        status="WARNING",
    )


def _remember(conversation: Dict[str, Any]) -> Dict[str, Any]:
    entry = _MEMORY.setdefault(conversation["conversation_id"], {"messages": []})
    entry["conversation"] = conversation
    while len(_MEMORY) > _MEMORY_LIMIT:
        _MEMORY.pop(next(iter(_MEMORY)))
    return entry


def fit_title(text: str) -> str:
    title = " ".join(text.split())
    return title if len(title) <= 60 else title[:59].rstrip() + "…"


async def create_conversation(owner_uid: str, title: Optional[str] = None) -> Dict[str, Any]:
    now = _now()
    record = {
        "conversation_id": uuid.uuid4().hex[:16],
        "owner_uid": owner_uid,
        "title": title[:TITLE_LIMIT] if title else None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        async with AsyncSessionLocal() as session:
            session.add(ConversationRecord(**record))
            await session.commit()
    except Exception as error:
        _remember(record)
        _warn("created", error)
    return _conversation(record)


async def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(ConversationRecord, conversation_id)
    except Exception:
        entry = _MEMORY.get(conversation_id)
        return _conversation(entry["conversation"]) if entry else None
    return _conversation(_columns(ConversationRecord, row)) if row else None


async def list_conversations(owner_uid: str, *, limit: int, offset: int) -> List[Dict[str, Any]]:
    """The owner's conversations, most recently active first.

    Only those with a saved exchange: a conversation gets its title from its
    first message, so an untitled one is a first message that was stopped or
    failed, and listing it would only show an empty "New conversation".
    """
    query = (
        select(ConversationRecord)
        .where(ConversationRecord.owner_uid == owner_uid, ConversationRecord.title.is_not(None))
        .order_by(ConversationRecord.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(query)).scalars().all()
    except Exception:
        owned = [
            e["conversation"]
            for e in _MEMORY.values()
            if e["conversation"]["owner_uid"] == owner_uid and e["conversation"]["title"]
        ]
        owned.sort(key=lambda c: c["updated_at"], reverse=True)
        return [_conversation(c) for c in owned[offset:offset + limit]]
    return [_conversation(_columns(ConversationRecord, row)) for row in rows]


async def get_messages(conversation_id: str) -> List[Dict[str, Any]]:
    query = (
        select(ConversationMessageRecord)
        .where(ConversationMessageRecord.conversation_id == conversation_id)
        .order_by(ConversationMessageRecord.position)
    )
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(query)).scalars().all()
    except Exception:
        entry = _MEMORY.get(conversation_id)
        return [_message(m) for m in entry["messages"]] if entry else []
    return [_message(_columns(ConversationMessageRecord, row)) for row in rows]


async def count_messages(conversation_id: str) -> int:
    query = select(func.count()).where(ConversationMessageRecord.conversation_id == conversation_id)
    try:
        async with AsyncSessionLocal() as session:
            return int(await session.scalar(query) or 0)
    except Exception:
        entry = _MEMORY.get(conversation_id)
        return len(entry["messages"]) if entry else 0


async def append_messages(
    conversation_id: str, messages: List[Dict[str, Any]], *, title: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Save a question and its answer together, so neither exists without the other."""
    start = await count_messages(conversation_id)
    now = _now()
    records = [
        {
            "message_id": uuid.uuid4().hex[:16],
            "conversation_id": conversation_id,
            "position": start + offset,
            "role": message["role"],
            "content": message["content"],
            "sources": message.get("sources") or [],
            "cited": message.get("cited") or [],
            "degraded": bool(message.get("degraded")),
            "created_at": now,
        }
        for offset, message in enumerate(messages)
    ]
    try:
        async with AsyncSessionLocal() as session:
            session.add_all(ConversationMessageRecord(**r) for r in records)
            conversation = await session.get(ConversationRecord, conversation_id)
            if conversation is not None:
                conversation.updated_at = now
                if title and not conversation.title:
                    conversation.title = title[:TITLE_LIMIT]
            await session.commit()
    except Exception as error:
        entry = _MEMORY.get(conversation_id)
        if entry is not None:
            entry["messages"].extend(records)
            entry["conversation"]["updated_at"] = now
            if title and not entry["conversation"]["title"]:
                entry["conversation"]["title"] = title[:TITLE_LIMIT]
        _warn("messages", error)
    return [_message(r) for r in records]


async def rename_conversation(conversation_id: str, title: str) -> None:
    title = title[:TITLE_LIMIT]
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(ConversationRecord, conversation_id)
            if row is not None:
                row.title = title
                await session.commit()
    except Exception:
        entry = _MEMORY.get(conversation_id)
        if entry:
            entry["conversation"]["title"] = title


async def delete_conversation(conversation_id: str) -> None:
    """Remove the conversation and every message in it."""
    _MEMORY.pop(conversation_id, None)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(ConversationMessageRecord).where(
                    ConversationMessageRecord.conversation_id == conversation_id
                )
            )
            await session.execute(
                delete(ConversationRecord).where(ConversationRecord.conversation_id == conversation_id)
            )
            await session.commit()
    except Exception:
        pass
