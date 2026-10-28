import time
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api.auth import LoginRateLimiter
from api.main import create_app
from repositories.auth_sessions import COOKIE


@pytest.fixture(scope='module')
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def sso_settings(settings, private_key):
    return settings.model_copy(update={
        'sso_enabled': True, 'sso_expected_target': 'atlas.test',
        'sso_public_key': private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
        'sso_expected_issuer': 'samsite', 'sso_expected_audience': '',
        'sso_cookie_secure': True, 'environment': 'production',
    })


def token(private_key, **overrides):
    now = int(time.time())
    claims = {'purpose': 'sso_login', 'iss': 'samsite', 'sub': 'user@example.test',
                  'email': 'User@example.test', 'jti': str(uuid4()), 'iat': now, 'nbf': now,
                  'exp': now + 600, 'target': 'atlas.test',
                  'user': {'nome': 'Nome SSO', 'email': 'untrusted@example.test',
                        'uid_user': 7, 'perfil': 'analista', '2fa_secret': 'ignored'}}
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm='RS256')


def browser(settings, *, development=False):
    return TestClient(create_app(settings, mcp=object(), client=object(), development=development),
                      base_url='https://atlas.test', follow_redirects=False)


def test_history_is_private_across_logins_and_restarts(sso_settings, private_key):
    from types import SimpleNamespace

    from core.history_identity import history_owner, identity_owner
    from core.models import Run
    from integrations.sso import Identity
    from repositories.local_store import now

    class LLM:
        def __init__(self):
            self.responses = self
            self.inputs = []

        async def create(self, **kwargs):
            self.inputs.append(kwargs)
            return SimpleNamespace(output=[], output_text='Análise concluída.')

    llm = LLM()
    app = create_app(sso_settings, mcp=object(), client=llm)
    with TestClient(app, base_url='https://atlas.test', follow_redirects=False) as client:
        assert client.post('/login', json={'token': token(private_key)}).status_code == 303
        first = client.post('/api/runs', json={'prompt': 'Histórico confidencial de A'}).json()
        first_id = first['id']
        assert client.get(f'/api/runs/{first_id}').status_code == 200
        session_id = client.post('/api/import-sessions').json()['session_id']
        scope = history_owner.set(identity_owner(Identity(email='user@example.test', name='A'), '',
                                                 sso_settings.sso_expected_issuer))
        try:
            artifact = app.state.store.save_artifact(first_id, 'Arquivo A', 'md', b'privado A')
            dataset = app.state.store.save_dataset([{'segredo': 'A'}], {}, first_id)
        finally:
            history_owner.reset(scope)
        # Legado sem dono: nunca atribuído ao primeiro usuário que entrar.
        legacy = Run(id=str(uuid4()), conversation_id=str(uuid4()), prompt='Legado sem dono',
                     status='completed', created_at=now(), updated_at=now())
        app.state.store.save_run(legacy)
        signed_b = token(private_key, sub='second@example.test', email='second@example.test')
        assert client.post('/login', json={'token': signed_b}).status_code == 303
        assert client.get('/api/conversations').json() == []
        assert client.get('/api/runs').json() == []
        assert client.get('/api/profile').json()['usage']['requests'] == 0
        assert client.get(f'/api/runs/{first_id}').status_code == 404
        assert client.get(f'/api/runs/{legacy.id}').status_code == 404
        assert client.post(f'/api/runs/{first_id}/cancel').status_code == 404
        assert client.post('/api/runs', json={'prompt': 'Continue',
                          'conversation_id': first['conversation_id']}).status_code == 404
        assert client.get(artifact['url']).status_code == 404
        assert client.get(f'/api/datasets/{dataset["id"]}').status_code == 404
        headers = {'X-Data-Session': session_id}
        assert client.get('/api/conversations', headers=headers).status_code == 410
        assert client.post('/api/import-sessions', headers=headers).status_code == 410
        assert client.delete('/api/import-sessions/current', headers=headers).status_code == 410
        assert session_id in app.state.imports.sessions
        second = client.post('/api/runs', json={'prompt': 'Pedido de B'}).json()
        assert [run['id'] for run in client.get('/api/conversations').json()] == [second['id']]
        assert 'Histórico confidencial de A' not in str(llm.inputs[-1]['input'])
        assert client.post('/login', json={'token': token(private_key)}).status_code == 303
        assert [run['id'] for run in client.get('/api/conversations').json()] == [first_id]
        assert client.get(artifact['url']).content == b'privado A'
        assert client.get(f'/api/runs/{second["id"]}').status_code == 404
    with browser(sso_settings) as client:
        assert client.post('/login', json={'token': token(private_key)}).status_code == 303
        assert [run['id'] for run in client.get('/api/conversations').json()] == [first_id]


@pytest.mark.parametrize('transport', ['form', 'json', 'bearer'])
def test_login_transports_profile_logout(sso_settings, private_key, transport):
    signed = token(private_key)
    with browser(sso_settings) as client:
        assert client.get('/api/profile').status_code == 401
        assert client.get('/').status_code == 401
        assert client.get('/health').status_code == 200
        kwargs = {'data': {'token': signed}}
        if transport == 'json':
            kwargs = {'json': {'token': signed}}
        if transport == 'bearer':
            kwargs = {'headers': {'Authorization': 'Bearer ' + signed}}
        response = client.post('/login', **kwargs)
        assert response.status_code == 303
        assert response.headers['location'] == '/'
        assert response.headers['cache-control'] == 'no-store'
        cookie = response.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=lax' in cookie
        assert signed not in cookie
        profile = client.get('/api/profile').json()
        assert profile['identity'] == 'user@example.test'
        assert profile['name'] == 'Nome SSO'
        assert 'privados' in profile['scope']
        assert client.get('/').status_code == 200
        assert client.post('/logout', headers={'Origin': 'https://evil.test'}).status_code == 403
        assert client.post('/logout').status_code == 204
        assert client.get('/api/profile').status_code == 401


@pytest.mark.parametrize('overrides', [
    {'purpose': 'other'}, {'target': 'other.test'}, {'target': None},
    {'iss': 'other'}, {'sub': 'other@example.test'}, {'email': ''},
    {'exp': 1}, {'nbf': 9999999999}, {'iat': 9999999999},
    {'jti': ''}, {'aud': 'unexpected'}, {'user': {'email': 'fake@example.test'}, 'sub': ''},
])
def test_invalid_claims(sso_settings, private_key, overrides):
    with browser(sso_settings) as client:
        response = client.post('/login', data={'token': token(private_key, **overrides)})
        assert response.status_code == 401
        assert COOKIE not in client.cookies


def test_signature_algorithm_and_missing_claim(sso_settings, private_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = jwt.decode(token(private_key), options={'verify_signature': False})
    del claims['exp']
    invalid = [token(other), jwt.encode(claims, private_key, algorithm='RS256'),
               jwt.encode(claims, 'a-test-only-secret-at-least-32-bytes', algorithm='HS256')]
    with browser(sso_settings) as client:
        for value in invalid:
            assert client.post('/login', json={'token': value}).status_code == 401


def test_audience_and_replay_across_instances(sso_settings, private_key):
    sso_settings.sso_expected_audience = 'atlas-audience'
    signed = token(private_key, aud='atlas-audience')
    with browser(sso_settings) as client:
        assert client.post('/login', data={'token': token(private_key)}).status_code == 401
        assert client.post('/login', data={'token': signed}).status_code == 303
        cookie = client.cookies.get(COOKIE)
    with browser(sso_settings) as client:
        client.cookies.set(COOKIE, cookie)
        assert client.get('/api/profile').status_code == 200
        assert client.post('/login', data={'token': signed}).status_code == 401
        with __import__('sqlite3').connect(sso_settings.data_dir / 'auth.sqlite3') as db:
            db.execute('UPDATE sessions SET expires = 0')
        assert client.get('/api/profile').status_code == 401


def test_get_development_and_logged_out(sso_settings):
    with browser(sso_settings) as client:
        assert client.get('/login').status_code == 405
    sso_settings.environment = 'development'
    sso_settings.environment_email = 'dev@example.test'
    sso_settings.environment_name = 'Developer'
    with browser(sso_settings, development=True) as client:
        assert client.get('/login?logged_out=1').status_code == 200
        assert client.get('/api/profile').status_code == 401
        assert client.get('/login').status_code == 303
        assert client.get('/api/profile').json()['identity'] == 'dev@example.test'


@pytest.mark.parametrize('environment,development,expected', [
    ('production', False, 405),
    ('production', True, 405),
    ('development', False, 405),
    ('development', True, 303),
])
def test_development_bypass_requires_environment_and_launcher_flag(
        sso_settings, environment, development, expected):
    sso_settings.environment = environment
    with browser(sso_settings, development=development) as client:
        assert client.get('/login').status_code == expected
        assert client.get('/api/profile').status_code == (200 if expected == 303 else 401)


def test_rate_limit_and_input_validation(sso_settings):
    with browser(sso_settings) as client:
        assert client.post('/login', json={'token': 42}).status_code == 400
        assert client.post('/login', content='token=x&token=y', headers={
            'Content-Type': 'application/x-www-form-urlencoded'}).status_code == 400
        assert client.post('/login', content='x' * 65537).status_code == 413
        for _ in range(7):
            assert client.post('/login').status_code == 401
        assert client.post('/login').status_code == 429


@pytest.mark.parametrize('environment,development,expected', [
    ('production', False, 405), ('production', True, 405),
    ('development', False, 405), ('development', True, 303),
])
def test_login_without_sso_configuration(settings, environment, development, expected):
    settings.sso_enabled = False
    settings.sso_public_key = ''
    settings.sso_public_key_path = None
    settings.sso_expected_target = ''
    settings.environment = environment
    settings.environment_email = 'local@example.test'
    app = create_app(settings, development=development, mcp=object(), client=object())
    with TestClient(app, base_url='http://127.0.0.1:8080', follow_redirects=False) as client:
        response = client.get('/login')
        assert response.status_code == expected
        assert client.get('/favicon.ico').status_code == 204
        assert client.post('/login', json={'token': 'not-a-jwt'}).status_code == 503
        if expected == 303:
            assert 'Secure;' not in response.headers['set-cookie']
            assert client.get('/').status_code == 200
            assert client.get('/api/profile').json()['identity'] == 'local@example.test'
            assert client.post('/logout', headers={'Origin': 'http://127.0.0.1:8080'}).status_code == 204
            assert client.get('/api/profile').status_code == 401
            assert client.get('/login?logged_out=1').status_code == 200
            assert client.get('/api/profile').status_code == 401


def test_development_cookie_is_not_valid_without_runtime_bypass(sso_settings):
    sso_settings.environment = 'development'
    with browser(sso_settings, development=True) as client:
        assert client.get('/login').status_code == 303
        cookie = client.cookies.get(COOKIE)
    with browser(sso_settings) as client:
        client.cookies.set(COOKIE, cookie)
        assert client.get('/api/profile').status_code == 401


def test_existing_development_session_uses_current_environment_identity(settings):
    settings.sso_enabled = False
    settings.environment = 'development'
    settings.environment_name = 'Nome anterior'
    settings.environment_email = 'old@example.test'
    app = create_app(settings, development=True, mcp=object(), client=object())
    with TestClient(app, base_url='http://127.0.0.1:8080', follow_redirects=False) as client:
        assert client.get('/login').status_code == 303
        assert client.get('/api/profile').json()['name'] == 'Nome anterior'
        settings.environment_name = 'Nome atualizado'
        settings.environment_email = 'updated@example.test'
        profile = client.get('/api/profile').json()
        assert profile['name'] == 'Nome atualizado'
        assert profile['identity'] == 'updated@example.test'


def test_profile_exposes_only_allowed_professional_fields(sso_settings, private_key):
    user = {'nome': 'Ana Silva', 'perfil': 'Analista', 'cargo': 'Analista de Crédito',
            'funcao': 'Risco', 'departamento': 'Crédito', 'numero_pa': '001',
            'nome_pa': 'Central', '2fa_secret': 'discard-me', 'unknown': 'discard-me'}
    with browser(sso_settings) as client:
        assert client.post('/login', json={'token': token(private_key, user=user)}).status_code == 303
        profile = client.get('/api/profile').json()
        assert profile['role'] == 'Analista de Crédito'
        assert profile['function'] == 'Risco'
        assert profile['department'] == 'Crédito'
        assert profile['unit_number'] == '001'
        assert profile['unit_name'] == 'Central'
        assert profile['profile'] == 'Analista'
        assert profile['auth_mode'] == 'sso'
        assert 'discard-me' not in str(profile)


def test_old_identity_without_professional_fields_stays_compatible(sso_settings, private_key):
    with browser(sso_settings) as client:
        assert client.post('/login', json={'token': token(private_key, user={})}).status_code == 303
        profile = client.get('/api/profile').json()
        assert profile['role'] is None
        assert profile['unit_number'] is None
        assert profile['identity'] == 'user@example.test'


def test_rate_limiter_expiration(monkeypatch):
    limiter = LoginRateLimiter(limit=1, seconds=60)
    monkeypatch.setattr('api.auth.time.monotonic', lambda: 0)
    assert limiter.allow('ip')
    assert not limiter.allow('ip')
    monkeypatch.setattr('api.auth.time.monotonic', lambda: 61)
    assert limiter.allow('ip')


def test_handoff(sso_settings, private_key, monkeypatch):
    sso_settings.sso_auth_base_url = 'https://auth.test'
    from pydantic import SecretStr
    sso_settings.sso_exchange_secret = SecretStr('synthetic-exchange-test-secret')
    signed = token(private_key)
    original_client = httpx.AsyncClient

    def handle(request):
        assert request.url == 'https://auth.test/sso/exchange'
        assert request.headers['authorization'] == 'Bearer synthetic-exchange-test-secret'
        assert __import__('json').loads(request.content) == {'code': 'test-code', 'aud': 'atlas.test'}
        return httpx.Response(200, json={'token': signed})

    def mock_client(**kwargs):
        assert kwargs['verify'].verify_mode == __import__('ssl').CERT_REQUIRED
        return original_client(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr('integrations.sso.httpx.AsyncClient', mock_client)
    with browser(sso_settings) as client:
        assert client.post('/login', data={'code': 'test-code', 'aud': 'wrong'}).status_code == 401
        assert client.post('/login', data={'code': 'test-code'}).status_code == 303


def test_sso_requires_configuration_and_cannot_use_api_key(sso_settings):
    from pydantic import SecretStr
    sso_settings.app_api_key = SecretStr('synthetic-api-test-secret')
    with browser(sso_settings) as client:
        assert client.get('/api/profile', headers={
            'Authorization': 'Bearer synthetic-api-test-secret'}).status_code == 401
    sso_settings.sso_expected_target = ''
    with pytest.raises(ValueError):
        create_app(sso_settings)
