"""Catálogo e prévias usam somente MCP simulado, sem IA ou banco externo."""
import json

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.models import AgentError
from tools.data_tools import CATALOG_DATABASES, Toolbox, definitions, table_entries


class CatalogMCP:
    def __init__(self):
        self.calls = []
        self.tables = [{"table_name": 'Venda "Especial"', "table_schema": "public"}]
        self.rows = [{"valor": index, "nome": "<script>literal</script>"} for index in range(15)]

    async def discover(self):
        return ["list_databases", "list_tables", "describe_table", "query"]

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "list_databases":
            return {"databases": [{"datname": "cora"}, {"datname": "restrito"}]}
        if name == "list_tables":
            return {"tables": self.tables}
        if "has_schema_privilege" in arguments.get("sql", ""):
            return {"rows": [{"public_access": arguments["database"] == "cora"}]}
        return {"rows": self.rows}


async def test_preview_is_registered_bounded_quoted_and_preserves_source(settings, store):
    mcp = CatalogMCP()
    toolbox = Toolbox(settings, store, mcp, None)
    assert "preview_table" in {item["name"] for item in definitions()}
    await toolbox.call("list_databases", {})
    result = await toolbox.call("preview_table", {
        "database": "cora", "schema": "public", "table": 'Venda "Especial"',
    })
    query = mcp.calls[-1][1]
    assert query == {"database": "cora", "sql": 'SELECT * FROM "public"."Venda ""Especial""" LIMIT 10', "max_rows": 10}
    assert result["sample_only"] is True
    assert result["row_count"] == len(result["preview"]) == 10
    assert result["source"]["table"] == 'Venda "Especial"'
    assert result["source"]["schema"] == "public"
    assert result["source"]["database"] == "cora"
    assert result["possibly_truncated"] is True
    assert len(store.get_dataset(result["dataset_id"])["rows"]) == 10
    assert store.list_runs() == []


async def test_preview_rejects_undiscovered_database_and_table(settings, store):
    settings.allowed_databases = ["cora"]
    mcp = CatalogMCP()
    toolbox = Toolbox(settings, store, mcp, None)
    await toolbox.call("list_databases", {})
    for args in [{"database": "restrito", "table": "x"},
                 {"database": "cora", "table": 'x"; DELETE FROM vendas; --'}]:
        with pytest.raises(AgentError):
            await toolbox.call("preview_table", args)
    assert all(name != "query" for name, _ in mcp.calls)


async def test_empty_preview_and_smaller_configured_limit(settings, store):
    settings.max_query_rows = 2
    mcp = CatalogMCP()
    mcp.rows = []
    toolbox = Toolbox(settings, store, mcp, None)
    await toolbox.call("list_databases", {})
    result = await toolbox.call("preview_table", {"database": "cora", "table": 'Venda "Especial"'})
    assert result["preview"] == []
    assert result["sample_only"] is True
    assert result["source"]["max_rows"] == 2
    assert mcp.calls[-1][1]["sql"].endswith("LIMIT 2")


def test_catalog_api_filters_databases_and_exposes_preview_without_ai(settings):
    settings.allowed_databases = ["cora"]
    mcp = CatalogMCP()
    with TestClient(create_app(settings, mcp=mcp, client=object())) as client:
        assert client.get("/api/catalog/databases").json() == {"databases": ["cora"]}
        tables = client.get("/api/catalog/tables", params={"database": "cora"})
        assert tables.status_code == 200
        assert tables.json()["tables"] == [{"schema": "public", "table": 'Venda "Especial"'}]
        response = client.post("/api/catalog/preview", json={"database": "cora", "table": 'Venda "Especial"'})
        assert response.status_code == 200
        assert response.json()["sample_only"] is True
        dataset_id = response.json()["dataset_id"]
        assert client.get(f"/api/datasets/{dataset_id}").status_code == 200
        assert client.get("/api/runs").json() == []
        assert client.get("/api/catalog/tables", params={"database": "restrito"}).status_code == 503
        assert client.post("/api/catalog/preview", json={"database": "cora"}).status_code == 422


def test_catalog_only_shows_databases_with_public_usage(settings):
    mcp = CatalogMCP()
    with TestClient(create_app(settings, mcp=mcp, client=object())) as client:
        assert client.get("/api/catalog/databases").json() == {"databases": ["cora"]}
        assert client.get("/api/catalog/tables", params={"database": "restrito"}).status_code == 503
        assert not any(name == "list_tables" and args["database"] == "restrito" for name, args in mcp.calls)


async def test_public_access_failure_excludes_only_failed_database(settings, store):
    mcp = CatalogMCP()
    original = mcp.call

    async def call(name, args):
        if name == "list_databases":
            return ["synap", "cora"]
        if args.get("database") == "synap":
            raise AgentError("Sem acesso")
        return await original(name, args)

    mcp.call = call
    toolbox = Toolbox(settings, store, mcp, None)
    assert await toolbox.call("list_public_databases", {}) == {"databases": ["cora"]}


async def test_selector_limits_databases_before_checking_public(settings, store):
    calls = []

    class AccessibleMCP:
        async def call(self, name, args):
            calls.append((name, args))
            if name == "list_databases":
                return ["postgres", *reversed(CATALOG_DATABASES), "outra_base"]
            return {"rows": [{"public_access": True}]}

    toolbox = Toolbox(settings, store, AccessibleMCP(), None)
    assert await toolbox.call("list_public_databases", {}) == {"databases": list(CATALOG_DATABASES)}
    assert {args["database"] for name, args in calls if name == "query"} == set(CATALOG_DATABASES)
    settings.allowed_databases = ["cora", "hub", "postgres"]
    assert await toolbox.call("list_public_databases", {}) == {"databases": ["cora", "hub"]}


def test_selector_rejects_other_database_even_with_public_access(settings):
    mcp = CatalogMCP()
    with TestClient(create_app(settings, mcp=mcp, client=object())) as client:
        response = client.post("/api/catalog/preview", json={"database": "postgres", "table": "vendas"})
        assert response.status_code == 503
        assert mcp.calls == []


async def test_chat_tools_only_allow_the_six_user_databases(settings, store):
    mcp = CatalogMCP()
    original = mcp.call

    async def call(name, args):
        if name == "list_databases":
            return ["postgres", *reversed(CATALOG_DATABASES), "outra_base"]
        return await original(name, args)

    mcp.call = call
    toolbox = Toolbox(settings, store, mcp, None)
    assert await toolbox.call("list_databases", {}) == {"databases": list(CATALOG_DATABASES)}
    for name, args in [
        ("list_tables", {"database": "postgres"}),
        ("describe_table", {"database": "outra_base", "table": "vendas"}),
        ("query", {"database": "postgres", "sql": "SELECT 1"}),
        ("preview_table", {"database": "outra_base", "table": "vendas"}),
    ]:
        with pytest.raises(AgentError, match="database permitido"):
            await toolbox.call(name, args)
    assert mcp.calls == []
    settings.allowed_databases = ["postgres"]
    assert await toolbox.call("list_databases", {}) == {"databases": []}


def test_connection_status_does_not_expose_other_databases(settings):
    with TestClient(create_app(settings, mcp=CatalogMCP(), client=object())) as client:
        response = client.get("/api/connections/pg-mcp")
        assert response.status_code == 200
        assert response.json()["databases"] == {"databases": ["cora"]}


def test_catalog_auth_errors_and_timeout(settings, monkeypatch):
    from pydantic import SecretStr

    settings.app_api_key = SecretStr("local-test")
    mcp = CatalogMCP()
    with TestClient(create_app(settings, mcp=mcp, client=object())) as client:
        assert client.get("/api/catalog/databases").status_code == 401
        assert mcp.calls == []

        async def fail(*_):
            raise AgentError("MCP indisponível")

        monkeypatch.setattr(mcp, "call", fail)
        response = client.get("/api/catalog/databases", headers={"Authorization": "Bearer local-test"})
        assert response.status_code == 503
        assert response.json()["detail"] == "MCP indisponível"

        async def timeout(*_):
            raise TimeoutError

        monkeypatch.setattr(mcp, "call", timeout)
        response = client.get("/api/catalog/databases", headers={"Authorization": "Bearer local-test"})
        assert response.status_code == 503
        assert "Tempo esgotado" in response.json()["detail"]


@pytest.mark.parametrize("payload", [["vendas"], {"rows": [{"table": "vendas"}]},
                                     {"tables": [{"tablename": "vendas"}]}])
def test_catalog_table_shapes(payload):
    assert table_entries(payload, "financeiro") == [{"table": "vendas", "schema": "financeiro"}]
    assert json.dumps(payload)
