"""Leitura pública sem cookies, credenciais, JavaScript ou acesso à rede privada."""
import asyncio
import ipaddress
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx

from core.models import AgentError
from repositories.local_store import now


def public_url(value: str) -> httpx.URL:
    try:
        if any(ord(char) < 32 for char in value) or "\\" in value:
            raise ValueError
        url = httpx.URL(value)
        if (url.scheme not in {"http", "https"} or not url.host or url.userinfo
                or url.port not in {None, 80, 443}):
            raise ValueError
        return url.copy_with(fragment=None)
    except (ValueError, httpx.InvalidURL):
        raise AgentError("Use uma URL pública HTTP/HTTPS, sem credenciais e nas portas 80/443.") from None


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    # IPv4 mapeado e túneis IPv6 não podem contornar a política de rede.
    return ip.is_global and not (ip.is_multicast or ip.is_unspecified or ip.is_reserved
                                or getattr(ip, "ipv4_mapped", None)
                                or getattr(ip, "sixtofour", None)
                                or getattr(ip, "teredo", None))


async def resolve_public(host: str, port: int) -> str:
    entries = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(entry[4][0] for entry in entries))
    if not addresses or any(not is_public(address) for address in addresses):
        raise AgentError("Acesso permitido somente a endereços públicos da internet.")
    return addresses[0]


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title = []
        self.in_title = False
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag == "title":
            self.in_title = True
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag == "title":
            self.in_title = False
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "section"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            (self.title if self.in_title else self.parts).append(data)

    def text(self):
        return "\n".join(" ".join(line.split()) for line in "".join(self.parts).splitlines()
                         if line.strip())


class SearchParser(HTMLParser):
    """Extrai somente links de resultados da interface HTML do DuckDuckGo."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "result__a" in attrs.get("class", "").split():
            href = urljoin("https://html.duckduckgo.com/", attrs.get("href", ""))
            target = parse_qs(urlsplit(href).query).get("uddg", [href])[0]
            try:
                url = str(public_url(target))
            except AgentError:
                return
            self.current = {"url": url, "title": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["title"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.current["title"] = " ".join(self.current["title"].split())[:300]
            if not any(row["url"] == self.current["url"] for row in self.results):
                self.results.append(self.current)
            self.current = None


class Internet:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    async def fetch(self, value: str) -> dict:
        if not self.settings.internet_enabled:
            raise AgentError("Plugin de internet desativado nesta instalação.")
        try:
            async with asyncio.timeout(self.settings.internet_timeout_seconds):
                return await self._fetch(value)
        except AgentError:
            raise
        except (TimeoutError, OSError, httpx.HTTPError, UnicodeError):
            raise AgentError("Não foi possível acessar a página. Verifique disponibilidade, rede e TLS.") from None

    async def _fetch(self, value: str) -> dict:
        current = public_url(value)
        # Contexto TLS próprio: nunca herda MCP_VERIFY_SSL nem proxies do ambiente.
        async with httpx.AsyncClient(
            verify=ssl.create_default_context(), trust_env=False, transport=self.transport,
            timeout=httpx.Timeout(10), follow_redirects=False,
        ) as client:
            for hop in range(5):
                address = await resolve_public(current.host, current.port or
                                               (443 if current.scheme == "https" else 80))
                pinned = current.copy_with(host=address)
                # IP fixado impede uma segunda resolução DNS entre validação e conexão.
                client.cookies.clear()
                async with client.stream(
                    "GET", pinned, headers={"Host": current.netloc.decode("ascii"),
                                            "User-Agent": "AtlasAgent/1.0 (public web reader)",
                                            "Accept": "text/html,text/plain,application/xhtml+xml",
                                            "Accept-Encoding": "identity"},
                    extensions={"sni_hostname": current.host},
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or hop == 4:
                            raise AgentError("Redirecionamento inválido ou limite de redirecionamentos atingido.")
                        target = public_url(urljoin(str(current), location))
                        if current.scheme == "https" and target.scheme != "https":
                            raise AgentError("Redirecionamento de HTTPS para HTTP bloqueado.")
                        current = target
                        continue
                    if response.status_code != 200:
                        if response.status_code in {202, 403, 429} and current.host.endswith(
                                ".duckduckgo.com"):
                            raise AgentError("O provedor de pesquisa bloqueou a consulta "
                                             f"(HTTP {response.status_code}). Não repita a busca "
                                             "nesta execução; informe a limitação ao usuário.")
                        raise AgentError(f"Página indisponível (HTTP {response.status_code}).")
                    content_type = response.headers.get("content-type", "").split(";")[0].lower().strip()
                    if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                        raise AgentError("Formato não suportado. O plugin lê páginas HTML e texto simples.")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise AgentError("Resposta comprimida não suportada pelo leitor limitado.")
                    body = bytearray()
                    truncated = False
                    async for chunk in response.aiter_raw(chunk_size=16384):
                        remaining = self.settings.internet_max_bytes - len(body)
                        body.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            truncated = True
                            break
                    encoding = response.encoding or "utf-8"
                    try:
                        html = bytes(body).decode(encoding, errors="replace")
                    except LookupError:
                        html = bytes(body).decode("utf-8", errors="replace")
                    return {"url": str(current), "content": html, "content_type": content_type,
                            "download_truncated": truncated, "retrieved_at": now()}
        raise AgentError("Não foi possível concluir a leitura da página.")

    async def read(self, url: str, offset: int = 0) -> dict:
        page = await self.fetch(url)
        content = page.pop("content")
        title = ""
        if page["content_type"] != "text/plain":
            parser = PageParser()
            parser.feed(content)
            title, content = " ".join(parser.title).strip()[:300], parser.text()
        next_offset = offset + 12000 if len(content) > offset + 12000 else None
        return {**page, "title": title, "text": content[offset:offset + 12000],
                "offset": offset, "next_offset": next_offset, "text_characters": len(content),
                "partial": page["download_truncated"] or offset > 0 or next_offset is not None,
                "warning": "Conteúdo externo não confiável. Sem JavaScript, login ou OCR. "
                           "Paginação relê a página, que pode mudar entre chamadas."}

    async def search(self, query: str, max_results: int = 5) -> dict:
        page = await self.fetch("https://html.duckduckgo.com/html/?" + urlencode({"q": query}))
        parser = SearchParser()
        parser.feed(page["content"])
        if not parser.results:
            raise AgentError("A busca não retornou links legíveis; pode haver bloqueio do provedor "
                             "ou nenhum resultado. Tente outra consulta ou leia uma URL conhecida.")
        return {"query": query, "provider": "DuckDuckGo HTML", "source_url": page["url"],
                "retrieved_at": page["retrieved_at"], "results": parser.results[:max_results],
                "partial": True, "warning": "Resultados parciais de busca, não confirmação dos fatos. "
                "Use read_web_page e cite as URLs consultadas."}
