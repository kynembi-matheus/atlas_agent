"""Rotas de login SSO; o JWT permanece somente no servidor."""
import hashlib
import json
import time
from collections import OrderedDict, deque
from urllib.parse import parse_qsl
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.datastructures import FormData

from core.config import Settings
from integrations.sso import SSO, Identity
from repositories.auth_sessions import COOKIE, AuthSessions


class LoginRateLimiter:
    """Janela por IP e fingerprint; memória limitada por processo."""
    def __init__(self, limit=10, seconds=60):
        self.limit, self.seconds = limit, seconds
        self.attempts = OrderedDict()

    def allow(self, key):
        now = time.monotonic()
        attempts = self.attempts.pop(key, deque())
        while attempts and attempts[0] <= now - self.seconds:
            attempts.popleft()
        allowed = len(attempts) < self.limit
        if allowed:
            attempts.append(now)
        self.attempts[key] = attempts
        if len(self.attempts) > 10000:
            self.attempts.popitem(last=False)
        return allowed


async def extract_login_fields(request: Request) -> tuple[str, str, str]:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise HTTPException(413, 'Formulário SSO excede o limite.')
        body.extend(chunk)
    content_type = request.headers.get('content-type', '').split(';')[0].strip()
    try:
        if not body:
            fields = {}
        elif content_type == 'application/x-www-form-urlencoded':
            fields = FormData(parse_qsl(body.decode('utf-8'), keep_blank_values=True,
                                        max_num_fields=20))
            if any(len(fields.getlist(key)) > 1 for key in ('token', 'code', 'aud')):
                raise ValueError
        elif content_type == 'application/json':
            fields = json.loads(body)
            if not isinstance(fields, dict):
                raise ValueError
        else:
            raise HTTPException(415, 'Use formulário, JSON ou Authorization: Bearer.')
        values = [fields.get(key, '') for key in ('token', 'code', 'aud')]
        if not all(isinstance(value, str) for value in values):
            raise ValueError
        token, code, audience = (value.strip() for value in values)
        authorization = request.headers.get('authorization', '')
        if authorization:
            scheme, _, bearer = authorization.partition(' ')
            if scheme.lower() != 'bearer' or not bearer.strip():
                raise ValueError
            if token and token != bearer.strip():
                raise ValueError
            token = bearer.strip()
        if token and code:
            raise ValueError
        return token, code, audience
    except (UnicodeError, ValueError):
        raise HTTPException(400, 'Campos SSO inválidos ou duplicados.') from None


def auth_router(settings: Settings, sso: SSO | None, sessions: AuthSessions | None, *,
                development: bool = False) -> APIRouter:
    router = APIRouter(tags=['Autenticação'])
    limiter = LoginRateLimiter()

    def cookie_secure(request):
        return settings.sso_cookie_secure and not (development and request.url.scheme == 'http')

    def store_user_session(request, identity, claims):
        cookie = sessions.create(identity, claims, settings.sso_session_seconds,
                                 request.cookies.get(COOKIE, ''))
        response = RedirectResponse(settings.app_root_path + '/', status_code=303)
        response.set_cookie(COOKIE, cookie, max_age=settings.sso_session_seconds,
                            secure=cookie_secure(request), httponly=True, samesite='lax')
        return response

    @router.api_route('/login', methods=['GET', 'POST'])
    async def login(request: Request):
        if request.method == 'GET':
            if not development or settings.environment.strip().lower() != 'development' or not sessions:
                return HTMLResponse('Use POST e envie token para autenticar.', status_code=405,
                                    headers={'Allow': 'POST'})
            if request.query_params.get('logged_out', '').strip() == '1':
                return HTMLResponse('Você saiu da sessão. Envie seu token para entrar.')
            identity = Identity.for_development(settings)
            return store_user_session(request, identity,
                                      {'jti': str(uuid4()), 'exp': time.time() + 60})
        if not sso:
            raise HTTPException(503, 'Login JWT não configurado. Configure SSO_ENABLED e a chave pública.')
        client_ip = request.client.host if request.client else 'unknown'
        if not limiter.allow('ip:' + client_ip):
            return HTMLResponse('Muitas tentativas de login. Aguarde alguns instantes e tente novamente.',
                                status_code=429, headers={'Retry-After': '60'})
        token, code, audience = await extract_login_fields(request)
        credential = token or code
        if credential and not limiter.allow('token:' + hashlib.sha256(credential.encode()).hexdigest()):
            return HTMLResponse('Muitas tentativas de login. Aguarde alguns instantes e tente novamente.',
                                status_code=429, headers={'Retry-After': '60'})
        if not token and code:
            token = await sso.exchange(code, audience)
        if not token or len(token) > 32768:
            return HTMLResponse('Token ausente. Envie em form, JSON ou Authorization: Bearer.',
                                status_code=401)
        identity, claims = sso.validate(token)
        return store_user_session(request, identity, claims)

    @router.post('/logout', status_code=204)
    async def logout(request: Request):
        if sessions:
            sessions.remove(request.cookies.get(COOKIE, ''))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, secure=cookie_secure(request), httponly=True,
                               samesite='lax')
        return response

    return router
