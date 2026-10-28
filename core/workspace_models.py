"""Contratos de tarefas agendadas e colaboração controlada por sessão."""
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class ScheduleTask(BaseModel):
    """Agende uma tarefa única, diária ou semanal; não aceita fontes temporárias."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=100)
    prompt: str = Field(min_length=3, max_length=16000)
    run_at: AwareDatetime
    web_search_enabled: bool = False
    query_ids: list[UUID] = Field(default_factory=list, max_length=10)
    source_run_id: UUID | None = None
    plan_steps: list[str] = Field(default_factory=list, max_length=8)
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=10)
    output_format: Literal['auto', 'dashboard'] = 'auto'
    frequency: Literal['once', 'daily', 'weekly'] = 'once'
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    timezone: str = 'America/Sao_Paulo'

    @model_validator(mode='after')
    def recurrence(self):
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Fuso horário inválido.') from None
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError('Dias da semana devem estar entre zero e seis.')
        self.weekdays = sorted(set(self.weekdays))
        if self.frequency == 'weekly' and (not self.weekdays or self.run_at.astimezone(zone).weekday() not in self.weekdays):
            raise ValueError('Selecione os dias e uma data inicial em um dos dias escolhidos.')
        return self

    @field_validator('run_at')
    @classmethod
    def future(cls, value):
        if value <= datetime.now(UTC):
            raise ValueError('Escolha uma data e hora futuras.')
        return value.astimezone(UTC)


class CreateSubagent(BaseModel):
    """Crie um perfil auxiliar nesta sessão; no máximo dois perfis por sessão."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=60)
    instructions: str = Field(min_length=3, max_length=3000)


class DelegateTask(BaseModel):
    """Delegue uma tarefa a um subagente da sessão e obtenha suas evidências para síntese."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    subagent_id: UUID
    task: str = Field(min_length=3, max_length=6000)
    source_run_id: UUID | None = None


class ContextualDelegateRequest(DelegateTask):
    web_search_enabled: bool | None = None
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=10)
    query_ids: list[UUID] = Field(default_factory=list, max_length=10)
    output_format: Literal['auto', 'dashboard'] = 'auto'


class ExecutionOptions(BaseModel):
    web_search_enabled: bool = False
    output_format: Literal['auto', 'dashboard'] = 'auto'
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=10)
    query_ids: list[UUID] = Field(default_factory=list, max_length=10)


class StartSubagent(ExecutionOptions):
    """Crie um subagente e inicie imediatamente o pedido do chat."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    task: str = Field(min_length=3, max_length=6000)
    source_run_id: UUID | None = None


class SchedulePlanRequest(ExecutionOptions):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    prompt: str = Field(min_length=3, max_length=16000)
    source_run_id: UUID | None = None


class SchedulePlan(BaseModel):
    """Planejamento da tarefa futura, sem executar ou agendar ações."""
    title: str = Field(min_length=3, max_length=100)
    steps: list[str] = Field(min_length=1, max_length=8)


class ProposeSchedule(BaseModel):
    """Proponha repetir uma tarefa a partir do contexto atual, sem ativar agendamento."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=100)
    prompt: str = Field(min_length=3, max_length=16000)
    reason: str = Field(min_length=3, max_length=1000)
    suggested_run_at: AwareDatetime | None = None


class SubagentId(BaseModel):
    """Cancele a tarefa ativa de um subagente desta sessão."""
    model_config = ConfigDict(extra='forbid')
    subagent_id: UUID


class DelegateBatch(BaseModel):
    """Delegue até duas tarefas independentes em paralelo aos subagentes desta sessão."""
    model_config = ConfigDict(extra='forbid')
    assignments: list[DelegateTask] = Field(min_length=1, max_length=2)


class ListSubagents(BaseModel):
    """Liste os até dois subagentes desta sessão e o estado das suas tarefas."""
    model_config = ConfigDict(extra='forbid')


class WorkspaceRequest(BaseModel):
    conversation_id: UUID | None = None
