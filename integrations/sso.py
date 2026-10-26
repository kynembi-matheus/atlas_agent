"""Validação estrita do JWT ScdAuth e troca de códigos servidor a servidor."""
import ssl
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import HTTPException
from pydantic import BaseModel

from core.config import Settings


class Identity(BaseModel):
    email: str
    name: str
    uid: str | int | None = None
    perfil: str | None = None
    cargo: str | None = None
    funcao: str | None = None
    departamento: str | None = None
    numero_pa: str | int | None = None
    nome_pa: str | None = None
    foto_url: str | None = None

    @classmethod
    def for_development(cls, settings: Settings) -> 'Identity':
        return cls(email=settings.environment_email, uid='development',
                   name=settings.environment_name or settings.environment_email or 'development',
                   perfil=settings.environment_profile, cargo=settings.environment_role,
                   funcao=settings.environment_function, departamento=settings.environment_department,
                   numero_pa=settings.environment_unit_number, nome_pa=settings.environment_unit_name,
                   foto_url=settings.environment_photo_url)


class SSO:
    def __init__(self, settings: Settings):
        self.settings = settings
        target = urlsplit('https://' + settings.sso_expected_target)
        if (not target.hostname or target.netloc != settings.sso_expected_target
                or target.path or target.query or target.fragment or target.username
                or target.password or not settings.sso_expected_issuer):
            raise ValueError('Configure SSO_EXPECTED_TARGET como host[:porta] e SSO_EXPECTED_ISSUER.')
        pem = (settings.sso_public_key_path.read_text(encoding='utf-8')
               if settings.sso_public_key_path else settings.sso_public_key.replace('\\n', '\n'))
        self.key = load_pem_public_key(pem.encode())
        if not isinstance(self.key, RSAPublicKey):
            raise TypeError('SSO_PUBLIC_KEY deve ser uma chave pública RSA.')

    def validate(self, token: str) -> tuple[Identity, dict]:
        try:
            claims = jwt.decode(
                token, self.key, algorithms=['RS256'],
                issuer=self.settings.sso_expected_issuer,
                audience=self.settings.sso_expected_audience or None,
                options={'require': ['purpose', 'iss', 'sub', 'email', 'jti',
                                     'iat', 'nbf', 'exp', 'target']},
            )
            email = claims['email']
            if (claims['purpose'] != 'sso_login'
                    or claims['target'] != self.settings.sso_expected_target
                    or not isinstance(email, str) or len(email) > 320
                    or not email.strip() or email != email.strip() or '@' not in email
                    or claims['sub'] != email.lower()
                    or not isinstance(claims['jti'], str) or not claims['jti'].strip()
                    or len(claims['jti']) > 256):
                raise ValueError
            user = claims.get('user')
            name = user.get('nome') if isinstance(user, dict) else None
            user = user if isinstance(user, dict) else {}
            safe = {key: user[key] for key in ('perfil', 'cargo', 'funcao', 'departamento',
                                              'nome_pa', 'foto_url')
                    if isinstance(user.get(key), str)}
            number = user.get('numero_pa')
            if isinstance(number, (str, int)) and not isinstance(number, bool):
                safe['numero_pa'] = number
            uid = user.get('uid_user')
            if isinstance(uid, (str, int)) and not isinstance(uid, bool):
                safe['uid'] = uid
            return Identity(email=email.lower(), name=name[:200] if isinstance(name, str)
                            and name.strip() else email, **safe), claims
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError):
            raise HTTPException(401, 'Token SSO inválido ou expirado.') from None

    async def exchange(self, code: str, audience: str) -> str:
        settings = self.settings
        if audience and audience != settings.sso_expected_target:
            raise HTTPException(401, 'Destino SSO inválido.')
        url = urlsplit(settings.sso_auth_base_url)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or not settings.sso_exchange_secret.get_secret_value()):
            raise HTTPException(503, 'Troca SSO não configurada.')
        verify = ssl.create_default_context(
            cafile=str(settings.sso_auth_ca_bundle) if settings.sso_auth_ca_bundle else None)
        try:
            async with httpx.AsyncClient(verify=verify, timeout=5, follow_redirects=False) as client:
                response = await client.post(
                    settings.sso_auth_base_url.rstrip('/') + '/sso/exchange',
                    json={'code': code, 'aud': settings.sso_expected_target},
                    headers={'Authorization': 'Bearer ' + settings.sso_exchange_secret.get_secret_value()},
                )
                if response.status_code in {400, 401, 403}:
                    raise HTTPException(401, 'Código SSO inválido ou expirado.')
                response.raise_for_status()
                token = response.json()['token']
                if not isinstance(token, str) or not token or len(token) > 32768:
                    raise ValueError
                return token
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(502, 'Não foi possível concluir a troca SSO.') from None
