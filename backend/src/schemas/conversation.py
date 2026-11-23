"""Legal companion conversations, as the API sends them."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

MESSAGE_LIMIT = 4000


class Source(BaseModel):
    """A statute section an answer was given, numbered as the answer cites it."""

    n: int
    act: str
    short_act: str
    section_number: str
    title: str
    text: str
    truncated: bool = False
    source_url: Optional[str] = None
    weak: bool = Field(False, description="Matched the question only weakly; probably does not apply")


class Message(BaseModel):
    message_id: str
    role: str = Field(..., description="'user' or 'assistant'")
    content: str
    sources: List[Source] = []
    cited: List[int] = Field(default=[], description="The source numbers the answer cites, in order of use")
    degraded: bool = Field(False, description="True when the answering model was unavailable")
    created_at: Optional[str] = None


class ConversationSummary(BaseModel):
    conversation_id: str
    title: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Conversation(ConversationSummary):
    messages: List[Message] = []


class ConversationList(BaseModel):
    items: List[ConversationSummary]
    has_more: bool


class CreateConversation(BaseModel):
    title: Optional[str] = Field(None, max_length=200)


class RenameConversation(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Give the conversation a name.")
        return value.strip()


class SendMessage(BaseModel):
    content: str = Field(..., min_length=1, max_length=MESSAGE_LIMIT)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write a message first.")
        return value.strip()


class TurnDone(BaseModel):
    """The `done` event: the saved question and answer."""

    question: Message
    answer: Message
    title: Optional[str] = None
