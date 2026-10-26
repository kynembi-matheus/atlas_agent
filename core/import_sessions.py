"""Sessões isoladas para importações temporárias, com expiração e limpeza de órfãos."""
import asyncio
import time
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from agents.orchestrator import Agent, RunManager
from core.models import AgentError
from repositories.temporary_store import TemporaryStore, remove_session_directory


@dataclass
class ImportSession:
    id: str
    store: TemporaryStore
    manager: RunManager
    touched: float = field(default_factory=time.monotonic)
    importing: bool = False


class ImportSessions:
    def __init__(self, settings, persistent, mcp, client):
        temp_root = (settings.data_dir.parent / 'temp').resolve()
        self.root = temp_root / 'import-sessions'
        if self.root.is_symlink() or not self.root.resolve().is_relative_to(temp_root):
            raise AgentError('A área temporária precisa estar dentro da pasta temp da aplicação.')
        self.root.mkdir(parents=True, exist_ok=True)
        for path in self.root.iterdir():
            try:
                UUID(path.name)
            except ValueError:
                continue
            remove_session_directory(path, self.root)
        self.settings, self.persistent, self.mcp, self.client = settings, persistent, mcp, client
        self.sessions = {}
        self.ttl = 3600

    def create(self):
        if len(self.sessions) >= 100:
            raise AgentError('Limite de sessões temporárias atingido. Feche sessões antigas e tente novamente.')
        session_id = str(uuid4())
        store = TemporaryStore(self.persistent, self.root, session_id)
        manager = RunManager(Agent(self.settings, store, self.mcp, self.client))
        session = ImportSession(session_id, store, manager)
        self.sessions[session_id] = session
        return session

    def get(self, session_id: str):
        session = self.sessions.get(session_id)
        if session is None:
            raise AgentError('A sessão temporária expirou. Atualize a página e importe os dados novamente.')
        session.touched = time.monotonic()
        return session

    async def remove(self, session_id: str):
        session = self.sessions.pop(session_id, None)
        if session:
            await session.manager.close()
            session.store.close()

    async def cleanup(self):
        for session in list(self.sessions.values()):
            if not session.importing and not session.manager.tasks and time.monotonic() - session.touched > self.ttl:
                await self.remove(session.id)

    async def sweep(self):
        while True:
            await asyncio.sleep(60)
            await self.cleanup()

    async def close(self):
        for session_id in list(self.sessions):
            await self.remove(session_id)
