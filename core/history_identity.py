"""Escopo de usuário definido pelo servidor e propagado às tarefas assíncronas."""
import hashlib
from contextvars import ContextVar

history_owner: ContextVar[str | None] = ContextVar('history_owner', default=None)


def identity_owner(identity, browser_token: str, issuer: str = '') -> str:
    if identity:
        subject = identity.email.strip().lower() or str(identity.uid or '')
        value = f'identity:{issuer}:{subject}'
    else:
        value = f'browser:{browser_token}'
    return hashlib.sha256(value.encode('utf-8')).hexdigest()
