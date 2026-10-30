from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from core.config import Settings
from core.history_identity import history_owner
from repositories.local_store import Store
from repositories.token_usage import TokenUsage, QuotaError, MeteredClient, admitted, PostgresUsageStore

@pytest.mark.asyncio
async def test_usage_windows_isolation_and_admission(tmp_path):
    store = Store(tmp_path)
    meter = TokenUsage(Settings(usage_limit_6h=10, usage_limit_week=20))
    class Responses:
        async def create(self, **kwargs):
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=6, output_tokens=4))
    client = MeteredClient(SimpleNamespace(responses=Responses()), meter)
    token = history_owner.set('alice')
    try:
        await client.responses.create()
        assert meter.summary()['six_hours']['tokens'] == 10
        with pytest.raises(QuotaError, match=r'Libera\u00e7\u00e3o estimada: \d{2}/\d{2}/\d{4} \u00e0s \d{2}:\d{2} \(UTC[+-]\d{2}:\d{2}\)'):
            meter.check()
        admitted_token = admitted.set(True)
        try:
            await client.responses.create()
        finally:
            admitted.reset(admitted_token)
        assert meter.summary()['week']['tokens'] == 20
        meter.storage.records = [(o, datetime.now(timezone.utc) - timedelta(hours=5), i, n) for o, _, i, n in meter.storage.records]
        assert meter.summary()['six_hours']['tokens'] == 20
        meter.storage.records = [(o, datetime.now(timezone.utc) - timedelta(hours=7), i, n) for o, _, i, n in meter.storage.records]
        assert meter.summary()['six_hours']['tokens'] == 0
        with pytest.raises(QuotaError):
            meter.check()
        other = history_owner.set('bob')
        try:
            meter.check()
            assert meter.summary()['week']['tokens'] == 0
        finally:
            history_owner.reset(other)
    finally:
        history_owner.reset(token)

def test_missing_usage_is_reported(tmp_path):
    meter = TokenUsage(Settings())
    token = history_owner.set('alice')
    try:
        meter.record(SimpleNamespace(usage=None))
        assert meter.summary()['week']['unavailable'] == 1
    finally:
        history_owner.reset(token)


def test_postgres_initializes_usage_table_with_tls(tmp_path, monkeypatch):
    import repositories.token_usage as module
    statements = []
    connections = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=None):
            statements.append(sql)
            return self
    def connect(**kwargs):
        connections.append(kwargs)
        return Connection()
    monkeypatch.setattr(module.psycopg, 'connect', connect)
    settings = Settings(_env_file=None, pghost='db.example', pgport=5433, pgdatabase='atlas', pguser='agent', pgpassword='secret', pgsslrootcert='ca.pem')
    storage = PostgresUsageStore(settings)
    storage.close()
    assert any('CREATE TABLE IF NOT EXISTS atlas_agent_token_usage' in sql for sql in statements)
    assert connections[0]['sslmode'] == 'verify-full'
    assert connections[0]['host'] == 'db.example'
    assert connections[0]['port'] == 5433


def test_postgres_requires_configuration_without_connecting(tmp_path, monkeypatch):
    import repositories.token_usage as module
    monkeypatch.setattr(module.psycopg, 'connect', lambda **kwargs: pytest.fail('unexpected database connection'))
    with pytest.raises(RuntimeError, match='PGHOST'):
        PostgresUsageStore(Settings(_env_file=None, pghost='', pgdatabase='', pguser='', pgpassword=''))


def test_default_token_limits():
    settings = Settings(_env_file=None)
    assert settings.usage_limit_6h == 2000000
    assert settings.usage_limit_week == 15000000


def test_postgres_uses_trusted_windows_cas_and_cleans_up(tmp_path, monkeypatch):
    from pydantic import SecretStr
    import repositories.token_usage as module
    certs = lambda name: [(b'cert-' + name.encode(), 'x509_asn', True), (b'untrusted', 'x509_asn', set())]
    monkeypatch.setattr(module.ssl, 'enum_certificates', certs, raising=False)
    paths = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, *args): return self
    def connect(**kwargs):
        path = Path(kwargs['sslrootcert'])
        assert path.exists()
        assert path.read_text(encoding='ascii').count('BEGIN CERTIFICATE') == 2
        assert kwargs['sslmode'] == 'verify-full'
        paths.append(path)
        return Connection()
    from pathlib import Path
    monkeypatch.setattr(module.psycopg, 'connect', connect)
    settings = Settings(_env_file=None, pghost='db.example', pgdatabase='atlas', pguser='agent', pgpassword=SecretStr('secret'))
    storage = PostgresUsageStore(settings)
    storage.close()
    assert not paths[0].exists()


def test_postgres_explicit_ca_takes_priority(tmp_path, monkeypatch):
    import repositories.token_usage as module
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, *args): return self
    calls = []
    monkeypatch.setattr(module.psycopg, 'connect', lambda **kwargs: (calls.append(kwargs) or Connection()))
    settings = Settings(_env_file=None, pghost='db.example', pgdatabase='atlas', pguser='agent', pgpassword='secret', pgsslrootcert='explicit-ca.pem')
    storage = PostgresUsageStore(settings)
    assert calls[0]['sslrootcert'] == 'explicit-ca.pem'
    storage.close()
