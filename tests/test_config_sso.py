from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.config import Settings
from integrations.sso import SSO


def test_sso_key_path_accepts_existing_env_name(tmp_path, monkeypatch):
    monkeypatch.delenv('SSO_PUBLIC_KEY_PATH', raising=False)
    monkeypatch.delenv('PUBLIC_KEY_PATH', raising=False)
    env = tmp_path / '.env'
    env.write_text('PUBLIC_KEY_PATH=/example/public.pem\n', encoding='utf-8')

    settings = Settings(_env_file=env)
    assert str(settings.sso_public_key_path) == '/example/public.pem'


def test_sso_key_path_prefers_explicit_sso_name(tmp_path, monkeypatch):
    monkeypatch.delenv('SSO_PUBLIC_KEY_PATH', raising=False)
    monkeypatch.delenv('PUBLIC_KEY_PATH', raising=False)
    env = tmp_path / '.env'
    env.write_text('PUBLIC_KEY_PATH=/example/legacy.pem\n'
                   'SSO_PUBLIC_KEY_PATH=/example/sso.pem\n', encoding='utf-8')

    settings = Settings(_env_file=env)
    assert str(settings.sso_public_key_path) == '/example/sso.pem'


def test_legacy_jwt_settings_validate_scdauth_token(tmp_path, monkeypatch):
    for name in ('SSO_EXPECTED_ISSUER', 'SSO_EXPECTED_AUDIENCE',
                 'JWT_EXPECTED_ISSUER', 'JWT_EXPECTED_AUDIENCE'):
        monkeypatch.delenv(name, raising=False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = tmp_path / 'public.pem'
    public_key.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    env = tmp_path / '.env'
    env.write_text(f'PUBLIC_KEY_PATH={public_key}\nSSO_EXPECTED_TARGET=atlas.example\n'
                   'JWT_EXPECTED_ISSUER=atlas-issuer\nJWT_EXPECTED_AUDIENCE=atlas-audience\n',
                   encoding='utf-8')
    settings = Settings(_env_file=env)
    now = datetime.now(UTC)
    token = jwt.encode({'purpose': 'sso_login', 'iss': 'atlas-issuer',
                        'aud': 'atlas-audience', 'target': 'atlas.example',
                        'sub': 'user@example.com', 'email': 'user@example.com',
                        'jti': 'test-token', 'iat': now, 'nbf': now,
                        'exp': now + timedelta(minutes=5)}, key, algorithm='RS256')
    identity, _ = SSO(settings).validate(token)
    assert identity.email == 'user@example.com'


def test_sso_jwt_settings_take_precedence(tmp_path, monkeypatch):
    for name in ('SSO_EXPECTED_ISSUER', 'SSO_EXPECTED_AUDIENCE',
                 'JWT_EXPECTED_ISSUER', 'JWT_EXPECTED_AUDIENCE'):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / '.env'
    env.write_text('JWT_EXPECTED_ISSUER=legacy\nJWT_EXPECTED_AUDIENCE=legacy\n'
                   'SSO_EXPECTED_ISSUER=current\nSSO_EXPECTED_AUDIENCE=current\n',
                   encoding='utf-8')
    settings = Settings(_env_file=env)
    assert settings.sso_expected_issuer == 'current'
    assert settings.sso_expected_audience == 'current'
