"""Metadados privados de sessões, subagentes e agendamentos no SQLite existente."""
import json
import secrets
from datetime import datetime
from uuid import uuid4

from core.history_identity import history_owner
from core.models import AgentError
from core.schedule_recurrence import next_occurrence
from repositories.local_store import encode, now
from repositories.task_context import capture_context


class Workspaces:
    def __init__(self, store):
        self.store = store
        self.persistent = getattr(store, 'persistent', store)
        self.temporary = hasattr(store, 'workspace_subagents')
        with self.persistent.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subagents (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    slot INTEGER NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(owner_id, conversation_id, slot)
                );
                CREATE TABLE IF NOT EXISTS subagent_slots (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    slot INTEGER NOT NULL, temporary_session_id TEXT,
                    UNIQUE(owner_id, conversation_id, slot)
                );
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    run_at TEXT NOT NULL, status TEXT NOT NULL, run_id TEXT NOT NULL,
                    dashboard_profile TEXT, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scheduled_due ON scheduled_tasks(status, run_at);
                INSERT OR IGNORE INTO subagent_slots (id, owner_id, conversation_id, slot)
                    SELECT id, owner_id, conversation_id, slot FROM subagents;
            ''')

    def owner(self):
        owner = history_owner.get()
        if not owner:
            raise AgentError('Identifique o usuário antes de usar esta sessão.')
        return owner

    def owns(self, conversation_id):
        with self.persistent.connect() as db:
            return db.execute('SELECT 1 FROM workspaces WHERE id = ? AND owner_id = ?',
                              (conversation_id, self.owner())).fetchone() is not None

    def reserve(self):
        key = str(uuid4())
        with self.persistent.connect() as db:
            db.execute('INSERT INTO workspaces VALUES (?, ?)', (key, self.owner()))
        return key

    def list_subagents(self, conversation_id):
        with self.persistent.connect() as db:
            rows = db.execute('SELECT id, payload FROM subagents WHERE owner_id = ? AND conversation_id = ? ORDER BY slot',
                              (self.owner(), conversation_id)).fetchall()
        items = {row[0]: json.loads(row[1]) for row in rows}
        if self.temporary:
            items.update({key: value for key, value in self.store.workspace_subagents.items()
                          if value['conversation_id'] == conversation_id})
        return list(items.values())

    def get_subagent(self, conversation_id, key):
        return next((item for item in self.list_subagents(conversation_id) if item['id'] == key), None)

    def create_subagent(self, conversation_id, args, *, created_by='principal'):
        names = ['Ana', 'Bruno', 'Camila', 'Daniel', 'Elisa', 'Felipe', 'Gabriela', 'Lucas', 'Marina', 'Rafael']
        used = {profile['name'] for profile in self.list_subagents(conversation_id)}
        name = secrets.choice([value for value in names if value not in used] or names)
        item = {'id': str(uuid4()), 'conversation_id': conversation_id, 'name': name,
                'instructions': args.instructions, 'status': 'idle', 'task': '', 'answer': '',
                'error': None, 'run_id': None, 'created_at': now(), 'created_by': created_by,
                'independent_conversation_id': str(uuid4()) if created_by == 'user' else None}
        with self.persistent.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            slots = {row[0] for row in db.execute('SELECT slot FROM subagent_slots WHERE owner_id = ? AND conversation_id = ?',
                                                 (self.owner(), conversation_id))}
            if len(slots) >= 2:
                raise AgentError('Esta sessão já possui dois subagentes. Reutilize um deles.')
            slot = next(value for value in (1, 2) if value not in slots)
            if item['independent_conversation_id']:
                db.execute('INSERT INTO workspaces VALUES (?, ?)', (item['independent_conversation_id'], self.owner()))
            db.execute('INSERT INTO subagent_slots VALUES (?, ?, ?, ?, ?)',
                       (item['id'], self.owner(), conversation_id, slot,
                        self.store.root.name if self.temporary else None))
            if self.temporary:
                self.store.workspace_subagents[item['id']] = item
            else:
                db.execute('INSERT INTO subagents VALUES (?, ?, ?, ?, ?)',
                           (item['id'], self.owner(), conversation_id, slot, encode(item)))
        return item

    def discard_unstarted_subagent(self, item):
        """Desfaça a reserva quando o primeiro pedido não pôde entrar na fila."""
        current = self.get_subagent(item['conversation_id'], item['id'])
        if not current or current.get('run_id'):
            return
        with self.persistent.connect() as db:
            db.execute('DELETE FROM subagents WHERE id = ? AND owner_id = ?', (item['id'], self.owner()))
            db.execute('DELETE FROM subagent_slots WHERE id = ? AND owner_id = ?', (item['id'], self.owner()))
            db.execute('DELETE FROM workspaces WHERE id = ? AND owner_id = ?',
                       (item['independent_conversation_id'], self.owner()))
        if self.temporary:
            self.store.workspace_subagents.pop(item['id'], None)

    def save_subagent(self, item):
        if not self.get_subagent(item['conversation_id'], item['id']):
            raise AgentError('Subagente não encontrado nesta sessão.')
        if self.temporary:
            self.store.workspace_subagents[item['id']] = dict(item)
        else:
            with self.persistent.connect() as db:
                db.execute('UPDATE subagents SET payload = ? WHERE id = ? AND owner_id = ?',
                           (encode(item), item['id'], self.owner()))

    def user_agent_for(self, conversation_id):
        if self.temporary:
            for item in self.store.workspace_subagents.values():
                if item.get('independent_conversation_id') == conversation_id:
                    return item
        with self.persistent.connect() as db:
            row = db.execute("SELECT payload FROM subagents WHERE owner_id = ? AND json_extract(payload, '$.independent_conversation_id') = ?",
                             (self.owner(), conversation_id)).fetchone()
        return json.loads(row[0]) if row else None

    def schedule(self, conversation_id, args, dashboard_profile):
        if self.temporary and (self.store.datasets or self.store.has_conversation(conversation_id)):
            raise AgentError('Agendamentos precisam de fontes persistentes. Importações e conversas temporárias expiram ao fechar a sessão.')
        context = capture_context(self.store, conversation_id, args.source_run_id)
        ids = list(dict.fromkeys([*context.get('dataset_ids', []), *(str(key) for key in args.dataset_ids)]))
        if len(ids) > 10:
            raise AgentError('Selecione no máximo dez fontes para agendar.')
        if any(self.persistent.get_dataset(key) is None for key in ids):
            raise AgentError('Agendamentos precisam de fontes persistentes disponíveis.')
        context['dataset_ids'] = ids
        options = context.get('options', {})
        query_ids = list(dict.fromkeys([*options.get('query_ids', []), *(str(key) for key in args.query_ids)]))[:10]
        for key in query_ids:
            if self.persistent.get_query(str(key)) is None:
                raise AgentError('Consulta favorita não encontrada.')
        item = {**args.model_dump(mode='json'), 'id': str(uuid4()),
                'conversation_id': conversation_id, 'status': 'pending', 'run_id': str(uuid4()),
                'created_at': now(), 'error': None, 'context_snapshot': context,
                'source_run_id': context.get('source_run_id'), 'query_ids': query_ids,
                'web_search_enabled': args.web_search_enabled if 'web_search_enabled' in args.model_fields_set else options.get('web_search_enabled', False),
                'output_format': args.output_format if 'output_format' in args.model_fields_set else options.get('output_format', 'auto')}
        with self.persistent.connect() as db:
            db.execute('INSERT INTO scheduled_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                       (item['id'], self.owner(), conversation_id, args.run_at.isoformat(),
                        'pending', item['run_id'], dashboard_profile, encode(item)))
        return item

    def list_schedules(self):
        with self.persistent.connect() as db:
            rows = db.execute('SELECT payload FROM scheduled_tasks WHERE owner_id = ? ORDER BY run_at DESC',
                              (self.owner(),)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def cancel_schedule(self, key):
        with self.persistent.connect() as db:
            row = db.execute('SELECT payload FROM scheduled_tasks WHERE id = ? AND owner_id = ? AND status = ?',
                             (key, self.owner(), 'pending')).fetchone()
            if not row:
                return False
            item = {**json.loads(row[0]), 'status': 'cancelled'}
            return db.execute('UPDATE scheduled_tasks SET status = ?, payload = ? WHERE id = ? AND status = ?',
                              ('cancelled', encode(item), key, 'pending')).rowcount == 1

    def due(self):
        with self.persistent.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT id, owner_id, dashboard_profile, payload FROM scheduled_tasks WHERE status = 'pending' AND run_at <= ? ORDER BY run_at LIMIT 10", (now(),)).fetchall()
            for key, _, _, payload in rows:
                item = {**json.loads(payload), 'status': 'dispatching'}
                db.execute('UPDATE scheduled_tasks SET status = ?, payload = ? WHERE id = ?',
                           ('dispatching', encode(item), key))
        return [(owner, profile, json.loads(payload)) for _, owner, profile, payload in rows]

    def finish_schedule(self, item, status, error=None):
        item = {**item, 'status': status, 'error': error}
        with self.persistent.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT status, run_id FROM scheduled_tasks WHERE id = ?', (item['id'],)).fetchone()
            if not current or current[0] == 'cancelled' or current[1] != item['run_id']:
                return
            if status in {'completed', 'failed', 'cancelled'} and item.get('frequency', 'once') != 'once':
                next_at = next_occurrence(item, datetime.fromisoformat(now()))
                item.update(starts_at=item.get('starts_at', item['run_at']), last_run_id=item['run_id'],
                            last_status=status, run_at=next_at, run_id=str(uuid4()), status='pending')
                status = 'pending'
            db.execute('UPDATE scheduled_tasks SET status = ?, run_at = ?, run_id = ?, payload = ? WHERE id = ?',
                       (status, item['run_at'], item['run_id'], encode(item), item['id']))

    def recover_schedules(self):
        with self.persistent.connect() as db:
            rows = db.execute("SELECT payload FROM scheduled_tasks WHERE status IN ('dispatching', 'running')").fetchall()
        for (payload,) in rows:
            item = json.loads(payload)
            run = self.persistent.get_run(item['run_id'])
            self.finish_schedule(item, run.status if run else 'pending', run.error if run else None)
        with self.persistent.connect() as db:
            db.execute('DELETE FROM subagent_slots WHERE temporary_session_id IS NOT NULL')
            rows = db.execute("SELECT id, payload FROM subagents WHERE json_extract(payload, '$.status') IN ('running', 'queued')").fetchall()
            for key, payload in rows:
                item = {**json.loads(payload), 'status': 'failed',
                        'error': 'Tarefa interrompida pelo reinício da aplicação.'}
                db.execute('UPDATE subagents SET payload = ? WHERE id = ?', (encode(item), key))
