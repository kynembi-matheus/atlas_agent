from contextlib import asynccontextmanager
from datetime import timedelta

import integrations.pg_mcp as pg_module
from agents.orchestrator import make_client
from integrations.pg_mcp import PgMCP


async def test_ai_timeout_is_150_seconds(settings):
    client = make_client(settings)
    try:
        assert client.timeout.read == 150
    finally:
        await client.close()


async def test_mcp_response_timeout_is_150_seconds(settings, monkeypatch):
    captured = {}

    @asynccontextmanager
    async def transport(*args, **kwargs):
        captured.update(kwargs)
        yield None, None, None

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

    monkeypatch.setattr(pg_module, 'streamablehttp_client', transport)
    monkeypatch.setattr(pg_module, 'ClientSession', Session)
    mcp = PgMCP(settings)
    async with mcp.http_client() as client:
        assert client.timeout.read == 150
        assert client.timeout.connect == 30
    async with mcp.session():
        pass
    assert captured['sse_read_timeout'] == timedelta(seconds=150)
    assert captured['timeout'] == timedelta(seconds=30)
