"""Biblioteca local com propriedade e limite transacional por perfil."""
import json
from uuid import uuid4

from core.models import AgentError
from repositories.local_store import encode, now

LIMIT = 4


class Dashboards:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS dashboards (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS dashboards_owner ON dashboards(owner)')

    def list(self, owner):
        with self.store.connect() as db:
            rows = db.execute('SELECT payload FROM dashboards WHERE owner=? ORDER BY rowid DESC',
                              (owner,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get(self, owner, key):
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM dashboards WHERE owner=? AND id=?',
                             (owner, key)).fetchone()
        return json.loads(row[0]) if row else None

    def create(self, owner, values):
        if not owner:
            raise AgentError('Inicie um perfil local no navegador para criar dashboards.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM dashboards WHERE owner=?', (owner,)).fetchone()[0] >= LIMIT:
                raise AgentError('Limite de 4 dashboards atingido. Exclua um para criar outro.')
            item = {**values, 'id': str(uuid4()), 'created_at': now()}
            db.execute('INSERT INTO dashboards VALUES (?, ?, ?)', (item['id'], owner, encode(item)))
        return item

    def delete(self, owner, key):
        with self.store.connect() as db:
            return db.execute('DELETE FROM dashboards WHERE owner=? AND id=?', (owner, key)).rowcount > 0
