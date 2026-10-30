"""Páginas estáticas declarativas publicadas por link."""
from html import escape
from pydantic import BaseModel, ConfigDict, Field
from core.dashboard_identity import dashboard_owner
from core.models import AgentError
from repositories.local_store import now
import secrets

class SiteSection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=5000)

class Site(BaseModel):
    """Publique uma página estática pública com título, descrição e seções textuais. Não inclua dados privados: qualquer pessoa com o link pode acessá-la. Leia sites/SKILL.md."""
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default='', max_length=1000)
    sections: list[SiteSection] = Field(min_length=1, max_length=12)

class Sites:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sites (id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS sites_owner ON sites(owner)")

    def create(self, owner, spec):
        from repositories.local_store import encode
        if not owner:
            raise AgentError('Perfil necessário para criar um site.')
        item = {**spec.model_dump(), 'id': secrets.token_urlsafe(32), 'created_at': now()}
        with self.store.connect() as db:
            db.execute('INSERT INTO sites VALUES (?, ?, ?)', (item['id'], owner, encode(item)))
        return item

    def list(self, owner):
        import json
        with self.store.connect() as db:
            rows = db.execute('SELECT payload FROM sites WHERE owner=? ORDER BY rowid DESC', (owner,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_public(self, key):
        import json
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM sites WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def delete(self, owner, key):
        with self.store.connect() as db:
            return db.execute('DELETE FROM sites WHERE id=? AND owner=?', (key, owner)).rowcount > 0

def render_site(item):
    sections = ''.join('<section><h2>' + escape(x['title']) + '</h2><p>' + escape(x['text']).replace('\n', '<br>') + '</p></section>' for x in item['sections'])
    return ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(item['title']) + '</title><style>body{margin:0;font:16px/1.65 system-ui,sans-serif;color:#172b4d;background:#f5f8fb}header{background:#101d38;color:white;padding:64px max(24px,calc((100% - 900px)/2))}h1{font-size:clamp(2rem,5vw,3.5rem);line-height:1.1;margin:0 0 16px}header p{max-width:700px;color:#cbd8e8}main{max-width:900px;margin:auto;padding:32px 24px}section{background:white;border:1px solid #e0e6ef;border-radius:14px;padding:24px;margin-bottom:16px}h2{margin-top:0}p{overflow-wrap:anywhere}</style></head><body><header><h1>' + escape(item['title']) + '</h1><p>' + escape(item['description']) + '</p></header><main>' + sections + '</main></body></html>')
