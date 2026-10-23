import asyncio
import inspect
import unittest
from contextlib import contextmanager
from ipaddress import ip_network
from unittest.mock import MagicMock, patch

import server


class ServerDatabaseTests(unittest.TestCase):
    def test_list_databases_uses_configured_discovery_database(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            {"database": "cora"},
            {"database": "deskflow"},
        ]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor

        @contextmanager
        def fake_connection(database):
            self.assertEqual(database, "deskflow")
            yield connection

        with patch.object(server, "DISCOVERY_DATABASE", "deskflow"), patch.object(
            server, "_connection", fake_connection
        ):
            result = server.list_databases()

        self.assertEqual(result, [{"database": "cora"}, {"database": "deskflow"}])
        cursor.execute.assert_called_once()

    def test_list_databases_requires_bootstrap_database(self):
        with patch.object(server, "DISCOVERY_DATABASE", None):
            with self.assertRaisesRegex(RuntimeError, "PGDATABASE"):
                server.list_databases()

    def test_query_requires_database_in_mcp_schema(self):
        async def read_tools():
            return await server.mcp.list_tools()

        tools = asyncio.run(read_tools())
        query_tool = next(tool for tool in tools if tool.name == "query")
        self.assertIn("database", query_tool.input_schema["required"])

    def test_list_databases_has_no_arguments(self):
        async def read_tools():
            return await server.mcp.list_tools()

        tools = asyncio.run(read_tools())
        database_tool = next(tool for tool in tools if tool.name == "list_databases")
        self.assertEqual(database_tool.input_schema["properties"], {})

    def test_database_name_validation(self):
        self.assertEqual(server._validate_database(" cora "), "cora")
        with self.assertRaisesRegex(ValueError, "nao pode ser vazio"):
            server._validate_database(" ")
        with self.assertRaisesRegex(ValueError, "caractere invalido"):
            server._validate_database("cora\x00")
        with self.assertRaisesRegex(ValueError, "63 bytes"):
            server._validate_database("a" * 64)

    def test_database_is_a_required_function_argument(self):
        self.assertIs(
            inspect.signature(server.query).parameters["database"].default,
            inspect.Parameter.empty,
        )
        self.assertIs(
            inspect.signature(server.list_tables).parameters["database"].default,
            inspect.Parameter.empty,
        )

    def test_query_uses_database_selected_by_client(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"id": 1}]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor

        @contextmanager
        def fake_connection(database):
            self.assertEqual(database, "cora")
            yield connection

        with patch.object(server, "_connection", fake_connection):
            result = server.query("SELECT id FROM clientes", database="cora")

        self.assertEqual(result["rows"], [{"id": 1}])
        cursor.execute.assert_called_once()


class APIKeyMiddlewareTests(unittest.TestCase):
    API_KEY = "a" * 64

    def _request(self, headers=None):
        calls = []

        async def app(scope, receive, send):
            calls.append("app")
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": [],
                }
            )
            await send({"type": "http.response.body", "body": b""})

        async def send(message):
            calls.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "client": ("127.0.0.1", 12345),
            "headers": [
                (name.lower().encode("ascii"), value.encode("ascii"))
                for name, value in (headers or {}).items()
            ],
        }
        asyncio.run(server.APIKeyMiddleware(app, self.API_KEY)(scope, receive, send))
        return calls

    def test_missing_key_is_rejected_before_mcp_app(self):
        calls = self._request()
        self.assertNotIn("app", calls)
        self.assertEqual(calls[0]["status"], 401)
        self.assertIn(b"www-authenticate", dict(calls[0]["headers"]))

    def test_invalid_key_is_rejected(self):
        calls = self._request({"X-API-Key": "wrong"})
        self.assertNotIn("app", calls)
        self.assertEqual(calls[0]["status"], 401)

    def test_bearer_key_is_accepted(self):
        calls = self._request({"Authorization": f"Bearer {self.API_KEY}"})
        self.assertIn("app", calls)

    def test_x_api_key_is_accepted(self):
        calls = self._request({"X-API-Key": self.API_KEY})
        self.assertIn("app", calls)

    def test_client_outside_allowed_network_is_rejected(self):
        calls = []

        async def app(scope, receive, send):
            calls.append("app")

        async def send(message):
            calls.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "client": ("192.168.10.20", 12345),
            "headers": [(b"x-api-key", self.API_KEY.encode("ascii"))],
        }
        middleware = server.APIKeyMiddleware(
            app,
            self.API_KEY,
            allowed_client_networks=[ip_network("192.168.11.0/24")],
        )
        asyncio.run(middleware(scope, receive, send))

        self.assertNotIn("app", calls)
        self.assertEqual(calls[0]["status"], 403)

    def test_client_inside_allowed_network_is_accepted(self):
        calls = []

        async def app(scope, receive, send):
            calls.append("app")

        async def send(message):
            calls.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "client": ("192.168.11.20", 12345),
            "headers": [(b"x-api-key", self.API_KEY.encode("ascii"))],
        }
        middleware = server.APIKeyMiddleware(
            app,
            self.API_KEY,
            allowed_client_networks=[ip_network("192.168.11.0/24")],
        )
        asyncio.run(middleware(scope, receive, send))

        self.assertIn("app", calls)


if __name__ == "__main__":
    unittest.main()
