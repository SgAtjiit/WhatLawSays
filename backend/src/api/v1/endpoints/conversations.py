"""Legal companion: saved conversations about the user's situation.

Every route needs a signed-in user, and someone else's conversation answers
exactly like a missing one. Replies stream as server-sent events:

    event: sources  {"sources": [...]}            the sections, before any text
    event: delta    {"text": "..."}               a piece of the answer
    event: done     {"question", "answer", "title"}  both saved
    event: error    {"detail": "..."}             nothing was saved
"""

import json
import time
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from src.config import settings
from src.core import conversation_store as store
from src.core import legal_chat
from src.core.auth import User, require_user
from src.core.logger import pipeline_logger
from src.schemas.conversation import (
    Conversation,
    ConversationList,
    ConversationSummary,
    CreateConversation,
    RenameConversation,
    SendMessage,
    TurnDone,
)

router = APIRouter(prefix="/conversations", tags=["Legal companion"])

STAGE = "COMPANION API"
CONVERSATION_LIMIT = 200  # messages, both sides
_MESSAGE_HISTORY: Dict[str, List[float]] = {}
# Conversations with an answer still streaming. A second message would be
# answered without the first one's reply in its history.
_ANSWERING: set = set()


def _enforce_rate_limit(uid: str) -> None:
    now = time.time()
    recent = [t for t in _MESSAGE_HISTORY.get(uid, []) if now - t < 60]
    if len(recent) >= settings.RATE_LIMIT_PER_MINUTE:
        pipeline_logger.log_step(STAGE, f"Message rate limit exceeded for user [{uid}]", status="WARNING")
        raise HTTPException(
            status_code=429,
            detail=f"That's {settings.RATE_LIMIT_PER_MINUTE} messages in a minute. Wait a moment, then send it again.",
        )
    recent.append(now)
    _MESSAGE_HISTORY[uid] = recent


async def _owned(conversation_id: str, user: User):
    conversation = await store.get_conversation(conversation_id)
    if conversation is None or conversation["owner_uid"] != user.uid:
        raise HTTPException(status_code=404, detail="We can't find that conversation.")
    return conversation


def _public(conversation) -> dict:
    return {k: v for k, v in conversation.items() if k != "owner_uid"}


@router.get("", response_model=ConversationList)
async def list_conversations(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_user),
):
    rows = await store.list_conversations(user.uid, limit=limit + 1, offset=offset)
    return {"items": [_public(r) for r in rows[:limit]], "has_more": len(rows) > limit}


@router.post("", response_model=ConversationSummary, status_code=201)
async def create_conversation(payload: CreateConversation, user: User = Depends(require_user)):
    return _public(await store.create_conversation(user.uid, payload.title))


@router.get("/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str, user: User = Depends(require_user)):
    conversation = await _owned(conversation_id, user)
    return {**_public(conversation), "messages": await store.get_messages(conversation_id)}


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str, payload: RenameConversation, user: User = Depends(require_user)
):
    await _owned(conversation_id, user)
    await store.rename_conversation(conversation_id, payload.title)
    return _public(await store.get_conversation(conversation_id))


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, user: User = Depends(require_user)):
    await _owned(conversation_id, user)
    await store.delete_conversation(conversation_id)
    return Response(status_code=204)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str, payload: SendMessage, user: User = Depends(require_user)
):
    conversation = await _owned(conversation_id, user)
    history = await store.get_messages(conversation_id)
    if len(history) + 2 > CONVERSATION_LIMIT:
        raise HTTPException(
            status_code=409,
            detail="This conversation is full. Start a new one; it can pick up where this left off.",
        )
    if conversation_id in _ANSWERING:
        raise HTTPException(status_code=409, detail="Wait for the current answer to finish.")
    _enforce_rate_limit(user.uid)
    _ANSWERING.add(conversation_id)
    title = None if conversation["title"] else store.fit_title(payload.content)

    async def events():
        try:
            turns = [{"role": m["role"], "content": m["content"]} for m in history]
            async for item in legal_chat.answer(turns, payload.content):
                if item["event"] != "done":
                    yield _sse(item["event"], item["data"])
                    continue
                result = item["data"]
                # Saved only once the answer is complete: a stopped or failed
                # reply leaves no half-answer in the record.
                question, reply = await store.append_messages(
                    conversation_id,
                    [
                        {"role": "user", "content": payload.content},
                        {
                            "role": "assistant",
                            "content": result["content"],
                            "sources": result["sources"],
                            "cited": result["cited"],
                            "degraded": result["degraded"],
                        },
                    ],
                    title=title,
                )
                done = TurnDone(question=question, answer=reply, title=title or conversation["title"])
                yield _sse("done", done.model_dump())
        finally:
            _ANSWERING.discard(conversation_id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
