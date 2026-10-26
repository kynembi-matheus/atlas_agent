from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    output_format: Literal['auto', 'dashboard'] = 'auto'
    prompt: str = Field(min_length=1, max_length=16000)
    conversation_id: UUID | None = None
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=10)
    query_ids: list[UUID] = Field(default_factory=list, max_length=10)


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


class UsageStatistics(BaseModel):
    conversations: int = Field(ge=0)
    requests: int = Field(ge=0)
    completed: int = Field(ge=0)
    artifacts: int = Field(ge=0)


class LocalProfile(BaseModel):
    name: str = "Usuário"
    identity: str = "Perfil local"
    profile: str | None = None
    role: str | None = None
    function: str | None = None
    department: str | None = None
    unit_number: str | int | None = None
    unit_name: str | None = None
    auth_mode: Literal['local', 'sso', 'development'] = 'local'
    scope: str = "Histórico compartilhado desta instalação e sessão temporária atual."
    usage: UsageStatistics


class AgentError(Exception):
    """Erro com mensagem segura para o usuário e o modelo."""
