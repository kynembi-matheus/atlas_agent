"""Contratos do plugin com HTTP/DNS simulados, sem internet, IA ou banco reais."""
import asyncio
import socket

import httpx
import pytest

from core.models import AgentError
from integrations import internet
from integrations.internet import Internet, public_url
from tools.data_tools import Toolbox, definitions


@pytest.fixture
def public_dns(monkeypatch):
    async def resolve(host, port):
        return "93.184.216.34"
    monkeypatch.setattr(internet, "resolve_public", resolve)


def response(text, *, status=200, headers=None):
    return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8",
                                          **(headers or {})},
                          stream=httpx.ByteStream(text.encode("utf-8")))


async def test_reads_text_and_pins_dns_with_tls_hostname(settings, public_dns):
    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.org"
        assert request.extensions["sni_hostname"] == "example.org"
        assert "authorization" not in request.headers
        return response('<title>Notícias</title><script>segredo()</script>'
                        '<style>invisível</style><p>Inflação &amp; crédito</p>')
    result = await Internet(settings, transport=httpx.MockTransport(handler)).read(
        "https://example.org/noticias")
    assert result["url"] == "https://example.org/noticias"
    assert result["title"] == "Notícias"
    assert result["text"] == "Inflação & crédito"
    assert result["retrieved_at"]
    assert result["partial"] is False


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.org/a",
    "https://user:password@example.org/", "https://example.org:8080/",
    "https://example.org/\nsecret", "https://example.org\\@localhost/"])
def test_rejects_invalid_urls(url):
    with pytest.raises(AgentError):
        public_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.114.16", "169.254.169.254",
    "192.168.1.1", "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "fe80::1",
    "::ffff:127.0.0.1", "2002:7f00:1::"])
async def test_private_dns_is_blocked(monkeypatch, address):
    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    with pytest.raises(AgentError, match="públicos"):
        await internet.resolve_public("example.org", 443)


async def test_mixed_public_private_dns_is_blocked(monkeypatch):
    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
                for ip in ["93.184.216.34", "127.0.0.1"]]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    with pytest.raises(AgentError):
        await internet.resolve_public("example.org", 443)


async def test_redirect_revalidates_dns(settings, monkeypatch):
    hosts = []
    async def resolve(host, port):
        hosts.append(host)
        if host == "internal.example":
            raise AgentError("Acesso permitido somente a endereços públicos da internet.")
        return "93.184.216.34"
    monkeypatch.setattr(internet, "resolve_public", resolve)
    requests = []
    def handler(request):
        requests.append(request)
        return response("", status=302, headers={"location": "https://internal.example/"})
    with pytest.raises(AgentError, match="públicos"):
        await Internet(settings, transport=httpx.MockTransport(handler)).read("https://example.org/")
    assert hosts == ["example.org", "internal.example"]
    assert len(requests) == 1


async def test_redirects_use_public_url_and_do_not_forward_cookies(settings, public_dns):
    def handler(request):
        assert "cookie" not in request.headers
        if request.url.path == "/first":
            return response("", status=302, headers={"location": "/next", "set-cookie": "secret=abc"})
        return response("<p>Final</p>")
    result = await Internet(settings, transport=httpx.MockTransport(handler)).read(
        "https://example.org/first")
    assert result["url"] == "https://example.org/next"
    assert result["text"] == "Final"


@pytest.mark.parametrize("location", ["http://example.org/", "file:///secret"])
async def test_unsafe_redirect(settings, public_dns, location):
    transport = httpx.MockTransport(lambda _: response("", status=302, headers={"location": location}))
    with pytest.raises(AgentError):
        await Internet(settings, transport=transport).read("https://example.org/")


async def test_redirect_loop_is_bounded(settings, public_dns):
    requests = []
    def handler(request):
        requests.append(request)
        return response("", status=302, headers={"location": "/loop"})
    with pytest.raises(AgentError, match="limite"):
        await Internet(settings, transport=httpx.MockTransport(handler)).read("https://example.org/")
    assert len(requests) == 5


async def test_total_timeout_includes_dns(settings, monkeypatch):
    settings.internet_timeout_seconds = 1
    async def slow_dns(*args):
        await asyncio.sleep(5)
    monkeypatch.setattr(internet, "resolve_public", slow_dns)
    with pytest.raises(AgentError, match="Não foi possível"):
        await Internet(settings).read("https://example.org/")


async def test_pagination_and_download_limit(settings, public_dns):
    settings.internet_max_bytes = 16384
    transport = httpx.MockTransport(lambda _: response("a" * 20000,
                                                       headers={"content-type": "text/plain"}))
    reader = Internet(settings, transport=transport)
    first = await reader.read("https://example.org/")
    second = await reader.read("https://example.org/", first["next_offset"])
    assert first["next_offset"] == 12000
    assert len(first["text"]) == 12000
    assert len(second["text"]) == 4384
    assert second["next_offset"] is None
    assert first["partial"] and second["download_truncated"]


async def test_search_extracts_deduplicated_links(settings, public_dns):
    html = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa">'
            'Fonte <b>oficial</b></a><a class="result__a" href="https://example.org/a">Repetida</a>'
            '<a class="result__a" href="https://example.net/">Outra</a>'
            '<a class="result__a" href="javascript:alert(1)">Ruim</a>')
    def handler(request):
        assert request.url.params["q"] == "crédito atual"
        return response(html)
    result = await Internet(settings, transport=httpx.MockTransport(handler)).search("crédito atual", 1)
    assert result["results"] == [{"url": "https://example.org/a", "title": "Fonte oficial"}]
    assert result["partial"]


async def test_search_block_is_explicit(settings, public_dns):
    transport = httpx.MockTransport(lambda _: response("<p>Captcha</p>"))
    with pytest.raises(AgentError, match="bloqueio"):
        await Internet(settings, transport=transport).search("consulta")


async def test_http_202_is_a_provider_block(settings, public_dns):
    transport = httpx.MockTransport(lambda _: response("captcha", status=202))
    with pytest.raises(AgentError, match="provedor de pesquisa bloqueou"):
        await Internet(settings, transport=transport).search("consulta")


async def test_failed_search_is_not_retried_in_the_same_run(settings, store, monkeypatch):
    settings.internet_search_provider = 'duckduckgo'
    calls = []
    async def blocked(self, query, max_results):
        calls.append(query)
        raise AgentError("Provedor bloqueado (HTTP 202).")
    monkeypatch.setattr(Internet, 'search', blocked)
    toolbox = Toolbox(settings, store, None, None, web_enabled=True)
    with pytest.raises(AgentError, match="202"):
        await toolbox.call('search_web', {'query': 'primeira consulta'})
    with pytest.raises(AgentError, match="Não repita"):
        await toolbox.call('search_web', {'query': 'outra consulta'})
    assert calls == ['primeira consulta']


@pytest.mark.parametrize("headers,status", [({"content-type": "application/pdf"}, 200),
    ({"content-encoding": "gzip"}, 200), ({}, 403)])
async def test_unsupported_or_failed_response(settings, public_dns, headers, status):
    transport = httpx.MockTransport(lambda _: response("", status=status, headers=headers))
    with pytest.raises(AgentError):
        await Internet(settings, transport=transport).read("https://example.org/")


async def test_network_error_does_not_leak_payload(settings, public_dns):
    def handler(request):
        raise httpx.ConnectError("secret credential")
    with pytest.raises(AgentError) as error:
        await Internet(settings, transport=httpx.MockTransport(handler)).read("https://example.org/")
    assert "secret" not in str(error.value)


async def test_disabled_and_validated_tool_contracts(settings, store, monkeypatch):
    toolbox = Toolbox(settings, store, None, None)
    with pytest.raises(AgentError, match="Argumentos inválidos"):
        await toolbox.call("search_web", {"query": "  "})
    with pytest.raises(AgentError):
        await toolbox.call("read_web_page", {"url": "https://example.org/", "offset": -1})
    with pytest.raises(AgentError):
        await toolbox.call("search_web", {"query": "teste", "headers": {}})
    settings.internet_enabled = False
    with pytest.raises(AgentError, match="desativado"):
        await toolbox.call("search_web", {"query": "teste"})
    names = {item["name"] for item in definitions(internet_enabled=False)}
    assert not names & {"search_web", "read_web_page"}
    settings.internet_enabled = True
    async def read(self, url, offset):
        return {"url": url, "offset": offset, "text": "Evidência"}
    monkeypatch.setattr(Internet, "read", read)
    assert await toolbox.call("read_web_page", {"url": "https://example.org/"}) == {
        "url": "https://example.org/", "offset": 0, "text": "Evidência"}
