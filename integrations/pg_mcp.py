"""Adaptador para o contrato pg_mcp existente (MCP Python SDK v1)."""
import json
import ssl

import httpx
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from core.config import Settings
from core.models import AgentError

ALLOWED_TOOLS = {"list_databases", "list_tables", "describe_table", "query"}


class PgMCP:
    def __init__(self, settings: Settings):
        self.settings = settings

    def http_client(self, headers=None, timeout=None, auth=None):
        verify = False
        if self.settings.mcp_verify_ssl:
            verify = ssl.create_default_context(
                cafile=str(self.settings.mcp_ca_bundle) if self.settings.mcp_ca_bundle else None
            )
        return httpx.AsyncClient(
            headers=headers, timeout=timeout or httpx.Timeout(30, read=150),
            auth=auth, verify=verify,
        )

    @asynccontextmanager
    async def session(self):
        headers = {}
        key = self.settings.mcp_api_key.get_secret_value()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            async with streamablehttp_client(
                self.settings.pg_mcp_url, headers=headers, timeout=timedelta(seconds=30),
                sse_read_timeout=timedelta(seconds=150), httpx_client_factory=self.http_client,
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        except AgentError:
            raise
        except Exception as exc:
            pending = [exc]
            while pending:
                error = pending.pop()
                if isinstance(error, AgentError):
                    raise AgentError(str(error)) from None
                if isinstance(error, httpx.HTTPStatusError):
                    if error.response.status_code == 403:
                        raise AgentError("pg_mcp: a rede de origem não está autorizada (403). Ajuste a allowlist no servidor.") from None
                    if error.response.status_code == 401:
                        raise AgentError("pg_mcp: chave de acesso recusada (401). Confira MCP_API_KEY.") from None
                pending.extend(getattr(error, "exceptions", []))
                if error.__cause__:
                    pending.append(error.__cause__)
            raise AgentError(
                "Falha no pg_mcp. Verifique endpoint, certificado, MCP_API_KEY e disponibilidade do serviço."
            ) from None

    async def call(self, name: str, arguments: dict):
        if name not in ALLOWED_TOOLS:
            raise AgentError("Ferramenta MCP não permitida.")
        async with self.session() as session:
            result = await session.call_tool(name, arguments)
            if result.isError:
                raise AgentError("O pg_mcp recusou a operação. Confira database, tabela e SQL.")
            structured = getattr(result, "structuredContent", None)
            if structured is not None:
                return structured.get("result", structured)
            parsed = []
            for block in result.content:
                if block.type == "text":
                    try:
                        parsed.append(json.loads(block.text))
                    except json.JSONDecodeError:
                        raise AgentError("Resposta MCP sem JSON estruturado compatível.") from None
            return parsed[0] if len(parsed) == 1 else parsed

    async def discover(self) -> list[str]:
        async with self.session() as session:
            result = await session.list_tools()
            return sorted(tool.name for tool in result.tools if tool.name in ALLOWED_TOOLS)
