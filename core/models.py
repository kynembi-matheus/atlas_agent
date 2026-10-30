from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from core.workspace_models import DelegateTask, ExecutionOptions


class RunRequest(BaseModel):
    subagent_tasks: list[DelegateTask] = Field(default_factory=list, max_length=2)
    web_search_enabled: bool = False
    work_enabled: bool = False
    output_format: Literal['auto', 'dashboard', 'sites'] = 'auto'
    prompt: str = Field(min_length=1, max_length=16000)
    conversation_id: UUID | None = None
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=10)
    query_ids: list[UUID] = Field(default_factory=list, max_length=10)


class Run(BaseModel):
    agent_profile_id: str | None = None
    origin_conversation_id: str | None = None
    execution_options: ExecutionOptions = Field(default_factory=ExecutionOptions)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    parent_run_id: str | None = None
    title: str = Field(default='', max_length=80)
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
    photo_url: str | None = None
    auth_mode: Literal['local', 'sso', 'development'] = 'local'
    scope: str = "Suas sessões e seus arquivos são privados. Consultas favoritas são compartilhadas nesta instalação."
    usage: UsageStatistics


class AgentError(Exception):
    """Erro com mensagem segura para o usuário e o modelo."""
