import ssl
import tempfile
from pathlib import Path
from contextvars import ContextVar
from uuid import uuid4

import psycopg
from datetime import datetime, timedelta, timezone
from core.history_identity import history_owner
from core.models import AgentError

admitted = ContextVar('usage_admitted', default=False)

class QuotaError(AgentError):
    pass

class PostgresUsageStore:
    """Dedicated writable storage; independent of the read-only MCP."""
    def __init__(self, settings):
        self.settings = settings
        if not all((settings.pghost, settings.pgdatabase, settings.pguser, settings.pgpassword.get_secret_value())):
            raise RuntimeError('Configure PGHOST, PGPORT, PGDATABASE, PGUSER e PGPASSWORD para o consumo de IA.')
        self._cert_dir = None
        self._sslrootcert = str(settings.pgsslrootcert) if settings.pgsslrootcert else None
        if not self._sslrootcert and hasattr(ssl, 'enum_certificates'):
            self._cert_dir = tempfile.TemporaryDirectory(prefix='atlas-pg-ca-')
            try:
                pem = []
                for store_name in ('ROOT', 'CA'):
                    for der, encoding, trust in ssl.enum_certificates(store_name):
                        if encoding == 'x509_asn' and (trust is True or (trust and '1.3.6.1.5.5.7.3.1' in trust)):
                            pem.append(ssl.DER_cert_to_PEM_cert(der))
                if not pem:
                    raise RuntimeError('Nenhuma autoridade certificadora confiável encontrada no Windows para PostgreSQL.')
                path = Path(self._cert_dir.name) / 'trusted-ca.pem'
                path.write_text(''.join(pem), encoding='ascii')
                self._sslrootcert = str(path)
            except Exception:
                self.close()
                raise
        try:
            with self.connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS atlas_agent_token_usage (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, recorded_at TIMESTAMPTZ NOT NULL,
                    input_tokens BIGINT, output_tokens BIGINT)""")
                db.execute('CREATE INDEX IF NOT EXISTS atlas_agent_token_usage_owner_time ON atlas_agent_token_usage(owner_id, recorded_at)')
        except psycopg.Error as exc:
            self.close()
            if 'certificate verify failed' in str(exc).lower() or 'root certificate file' in str(exc).lower():
                raise RuntimeError('Certificado PostgreSQL não confiável. Configure PGSSLROOTCERT com a CA correta ou instale a CA confiável no Windows.') from None
            raise RuntimeError('Não foi possível inicializar o armazenamento PostgreSQL de consumo. Confira conexão, TLS e permissões.') from None

    def connect(self):
        s = self.settings
        options = {'sslrootcert': self._sslrootcert} if self._sslrootcert else {}
        return psycopg.connect(host=s.pghost, port=s.pgport, dbname=s.pgdatabase, user=s.pguser,
                               password=s.pgpassword.get_secret_value(), sslmode=s.pgsslmode, connect_timeout=10, **options)

    def close(self):
        if self._cert_dir is not None:
            self._cert_dir.cleanup()
            self._cert_dir = None

    def recent(self, owner, cutoff):
        try:
            with self.connect() as db:
                return db.execute('SELECT recorded_at, input_tokens, output_tokens FROM atlas_agent_token_usage WHERE owner_id = %s AND recorded_at > %s ORDER BY recorded_at', (owner, cutoff)).fetchall()
        except psycopg.Error:
            raise AgentError('Não foi possível consultar o consumo de IA. Tente novamente.') from None

    def record(self, owner, timestamp, input_tokens, output_tokens):
        try:
            with self.connect() as db:
                db.execute('INSERT INTO atlas_agent_token_usage VALUES (%s, %s, %s, %s, %s)',
                           (str(uuid4()), owner, timestamp, input_tokens, output_tokens))
        except psycopg.Error:
            raise AgentError('Não foi possível registrar o consumo de IA. Tente novamente.') from None


class TokenUsage:
    def __init__(self, settings):
        self.settings = settings
        self.storage = PostgresUsageStore(settings)

    def close(self):
        close = getattr(self.storage, 'close', None)
        if close:
            close()

    def summary(self):
        owner = history_owner.get()
        current = datetime.now(timezone.utc)
        rows = self.storage.recent(owner, current - timedelta(days=7))
        result = {}
        for key, period, limit in [('six_hours', timedelta(hours=6), self.settings.usage_limit_6h), ('week', timedelta(days=7), self.settings.usage_limit_week)]:
            entries = [(t, i, o) for t, i, o in rows if t > current - period]
            total = sum((i or 0) + (o or 0) for _, i, o in entries)
            remaining = max(0, limit - total)
            release = None
            if not remaining:
                excess = total - limit
                for t, i, o in entries:
                    excess -= (i or 0) + (o or 0)
                    if excess < 0:
                        release = (t + period).isoformat()
                        break
            result[key] = {'tokens': total, 'limit': limit, 'remaining': remaining, 'available_at': release, 'unavailable': sum(i is None or o is None for _, i, o in entries)}
        return result

    def check(self):
        if history_owner.get() is None:
            raise QuotaError('Não foi possível identificar o usuário para verificar o limite de IA.')
        for name, window in self.summary().items():
            if not window['remaining']:
                release = datetime.fromisoformat(window['available_at']).astimezone()
                offset = release.strftime('%z')
                formatted = release.strftime('%d/%m/%Y às %H:%M') + f' (UTC{offset[:3]}:{offset[3:]})'
                label = 'de 6 horas' if name == 'six_hours' else 'semanal'
                raise QuotaError(f"Limite de tokens {label} atingido. Liberação estimada: {formatted}.")

    def record(self, response):
        usage = getattr(response, 'usage', None)
        i = getattr(usage, 'input_tokens', None)
        o = getattr(usage, 'output_tokens', None)
        self.storage.record(history_owner.get(), datetime.now(timezone.utc), i, o)

class MeteredResponses:
    def __init__(self, responses, meter):
        self._responses, self._meter = responses, meter
    async def create(self, **kwargs):
        if not admitted.get():
            self._meter.check()
        response = await self._responses.create(**kwargs)
        self._meter.record(response)
        return response
    def __getattr__(self, name):
        return getattr(self._responses, name)

class MeteredClient:
    def __init__(self, client, meter):
        self._client = client
        self._meter = meter
    @property
    def responses(self):
        return MeteredResponses(self._client.responses, self._meter)
    def __getattr__(self, name):
        return getattr(self._client, name)
