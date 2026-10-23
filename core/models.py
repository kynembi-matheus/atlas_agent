from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=16000)
    conversation_id: UUID | None = None
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=10)


class Run(BaseModel):
    id: str
    conversation_id: str
    prompt: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    created_at: str
    updated_at: str
    answer: str = ""
    error: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class AgentError(Exception):
    """Erro com mensagem segura para o usuário e o modelo."""
