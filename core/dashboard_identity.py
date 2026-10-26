"""Identidade local opaca, propagada também às tarefas assíncronas do agente."""
from contextvars import ContextVar

dashboard_owner = ContextVar('dashboard_owner', default=None)
