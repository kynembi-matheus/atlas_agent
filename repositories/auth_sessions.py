"""Sessões locais revogáveis; nenhum JWT ou cookie em texto é persistido."""
import hashlib
import secrets
import sqlite3
import time
from pathlib import Path

from fastapi import HTTPException

from integrations.sso import Identity

COOKIE = 'scd-sso-session'


class AuthSessions:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'auth.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, identity TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS consumed (
                    jti TEXT PRIMARY KEY, expires REAL NOT NULL
                );
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def create(self, identity: Identity, claims: dict, seconds: int, previous: str = '') -> str:
        cookie = secrets.token_urlsafe(32)
        now = time.time()
        try:
            with self.connect() as db:
                db.execute('DELETE FROM sessions WHERE expires <= ?', (now,))
                db.execute('DELETE FROM consumed WHERE expires <= ?', (now,))
                db.execute('INSERT INTO consumed VALUES (?, ?)',
                           (self.digest(claims['jti']), claims['exp']))
                db.execute('DELETE FROM sessions WHERE id = ?', (self.digest(previous),))
                db.execute('INSERT INTO sessions VALUES (?, ?, ?)',
                           (self.digest(cookie), identity.model_dump_json(), now + seconds))
        except sqlite3.IntegrityError:
            raise HTTPException(401, 'Token SSO já utilizado.') from None
        return cookie

    def get(self, cookie: str) -> Identity | None:
        if not cookie or len(cookie) > 128:
            return None
        with self.connect() as db:
            row = db.execute('SELECT identity FROM sessions WHERE id = ? AND expires > ?',
                             (self.digest(cookie), time.time())).fetchone()
        return Identity.model_validate_json(row[0]) if row else None

    def remove(self, cookie: str):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE id = ?', (self.digest(cookie),))
