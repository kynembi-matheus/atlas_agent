"""Biblioteca, refresh e agente sem IA ou PostgreSQL reais."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agents.orchestrator import Agent
from api.main import create_app
from core.dashboard_identity import dashboard_owner
from core.models import AgentError, Run, RunRequest
from repositories.dashboards import Dashboards
from tools.data_tools import Toolbox, definitions


class MCP:
    def __init__(self):
        self.value = 10
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, args))
        if name == 'list_databases':
            return ['cora']
        return {'rows': [{'grupo': '<script>x</script>', 'valor': self.value}]}


def specification(key, **changes):
    return {'title': 'Carteira <script>1</script>', 'description': 'Indicadores atuais',
            'widgets': [{'title': 'Saldo', 'dataset_id': key, 'kind': 'metric',
                         'value_column': 'valor', 'unit': 'R$'},
                        {'title': 'Por grupo', 'dataset_id': key, 'kind': 'bar',
                         'value_column': 'valor', 'label_column': 'grupo'},
                        {'title': 'Detalhes', 'dataset_id': key, 'kind': 'table',
                         'numeric_columns': ['valor'],
                         'columns': {'grupo': 'Grupo', 'valor': 'Valor'}}], **changes}


def postgres_dataset(store):
    return store.save_dataset([{'grupo': 'A', 'valor': 1}], {
        'kind': 'postgresql', 'database': 'cora', 'sql': 'SELECT grupo, valor FROM indicadores',
        'max_rows': 10, 'possibly_truncated': False})


def test_library_refresh_ownership_and_delete(settings, store, client_owner_scope):
    mcp = MCP()
    app = create_app(settings, mcp=mcp, client=object())
    with TestClient(app) as client:
        with client_owner_scope(client):
            key = postgres_dataset(store)['id']
        assert client.get('/dashboards').status_code == 200
        profile = client.cookies.get('scd-dashboard-profile')
        response = client.post('/api/dashboards', json=specification(key))
        assert response.status_code == 201
        item = response.json()
        assert item['format'] == 'dashboard'
        assert item['url'] == f"/dashboards/{item['id']}"
        assert client.get(item['url']).status_code == 200
        assert client.get('/api/dashboards/' + item['id']).json()['title'] == specification(key)['title']
        for _ in range(3):
            assert client.post('/api/dashboards', json=specification(key)).status_code == 201
        assert client.post('/api/dashboards', json=specification(key)).status_code == 422
        assert len(client.get('/api/dashboards').json()['dashboards']) == 4
        with store.connect() as db:
            before = db.execute('SELECT COUNT(*) FROM datasets').fetchone()[0]
        url = f"/api/dashboards/{item['id']}/html"
        html = client.get(url)
        assert html.status_code == 200
        assert html.headers['cache-control'] == 'no-store'
        assert '<script>' not in html.text
        assert '&lt;script&gt;' in html.text
        assert '10,00' in html.text
        mcp.value = 25
        assert '25,00' in client.get(url).text
        assert sum(name == 'query' for name, _ in mcp.calls) == 2  # fonte compartilhada
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM datasets').fetchone()[0] == before
        client.cookies.clear()
        assert client.get('/api/dashboards').json()['dashboards'] == []
        assert client.get(url).status_code == 404
        assert client.get('/api/dashboards/' + item['id']).status_code == 404
        assert client.delete(f"/api/dashboards/{item['id']}").status_code == 404
        client.cookies.set('scd-dashboard-profile', profile)
        assert client.delete(f"/api/dashboards/{item['id']}").status_code == 204
        assert client.post('/api/dashboards', json=specification(key)).status_code == 201
    assert len(Dashboards(store).list(profile)) == 4


def test_quota_is_atomic(store):
    def create(_):
        try:
            return Dashboards(store).create('profile', {'title': 'Um'})
        except AgentError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(12)))
    assert sum(item is not None for item in results) == 4
    assert len(Dashboards(store).list('profile')) == 4


async def test_transformations_are_replayed_and_permissions_rechecked(settings, store):
    from tools.dashboards import RefreshStore, refresh
    mcp = MCP()
    toolbox = Toolbox(settings, store, mcp, None)
    key = postgres_dataset(store)['id']
    transformed = await toolbox.call('transform_dataset', {
        'dataset_id': key, 'operations': [{'op': 'filter', 'column': 'valor',
                                         'comparison': 'gt', 'value': 15}]})
    token = dashboard_owner.set('tester')
    try:
        saved = await toolbox.call('create_dashboard', specification(transformed['dataset_id']))
    finally:
        dashboard_owner.reset(token)
    item = Dashboards(store).get('tester', saved['id'])
    assert "'rows':" not in str(item['sources'])
    fresh = lambda: Toolbox(settings, RefreshStore(store), mcp, None)
    assert 'Sem dados' in await refresh(fresh(), item)
    mcp.value = 30
    assert '30,00' in await refresh(fresh(), item)
    settings.allowed_databases = ['hub']
    before = sum(name == 'query' for name, _ in mcp.calls)
    with pytest.raises(AgentError, match='database permitido'):
        await refresh(fresh(), item)
    assert sum(name == 'query' for name, _ in mcp.calls) == before


def test_import_expiry_does_not_persist_rows(settings):
    app = create_app(settings, mcp=MCP(), client=object())
    with TestClient(app) as client:
        session = client.post('/api/import-sessions').json()['session_id']
        headers = {'X-Data-Session': session}
        store = app.state.imports.get(session).store
        data = store.save_dataset([{'grupo': 'CONFIDENTIAL', 'valor': 45}],
                                  {'kind': 'temporary_import', 'filename': 'arquivo.csv'})
        item = client.post('/api/dashboards', headers=headers, json=specification(data['id'])).json()
        url = f"/api/dashboards/{item['id']}/html"
        assert 'CONFIDENTIAL' in client.get(url, headers=headers).text
        saved = Dashboards(app.state.store).list(client.cookies.get('scd-dashboard-profile'))
        assert 'CONFIDENTIAL' not in str(saved)
        client.delete('/api/import-sessions/current', headers=headers)
        new_session = client.post('/api/import-sessions').json()['session_id']
        response = client.get(url, headers={'X-Data-Session': new_session})
        assert response.status_code == 422
        assert 'recriado' in response.json()['detail']


async def test_validation_and_agent_output(settings, store):
    mcp = MCP()
    toolbox = Toolbox(settings, store, mcp, None)
    key = store.save_dataset([{'valor': 1}, {'valor': 2}], {'kind': 'upload'})['id']
    with pytest.raises(AgentError, match='uma linha agregada'):
        await toolbox.call('create_dashboard', specification(key))
    assert 'create_dashboard' in {tool['name'] for tool in definitions()}
    captured = []
    async def respond(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(output=[], output_text='Pronto')
    agent = Agent(settings, store, mcp, SimpleNamespace(responses=SimpleNamespace(create=respond)))
    run = Run(id=str(uuid4()), conversation_id=str(uuid4()), prompt='Resumo',
              status='running', created_at='', updated_at='')
    await agent.execute(run, RunRequest(prompt='Resumo', output_format='dashboard'))
    assert 'Formato de saída solicitado: Dashboard' in captured[0]['input'][-1]['content']


def test_dashboard_auth(settings):
    from pydantic import SecretStr
    settings.app_api_key = SecretStr('test-access')
    with TestClient(create_app(settings, mcp=MCP(), client=object())) as client:
        assert client.get('/api/dashboards').status_code == 401
        assert client.post('/api/dashboards', json={}).status_code == 401


def test_charts_and_visible_sample_limits():
    from tools.dashboards import Dashboard, render_html
    data = {'id': 'data', 'rows': [{'grupo': 'Jan', 'valor': -5}, {'grupo': 'Fev', 'valor': 10}],
            'source': {'kind': 'postgresql', 'possibly_truncated': True}}
    widgets = [{'title': kind, 'dataset_id': 'data', 'kind': kind,
                'value_column': 'valor', 'label_column': 'grupo'} for kind in ('bar', 'line')]
    html = render_html(Dashboard(title='Gráficos', widgets=widgets), {'data': data})
    assert '<polyline' in html
    assert '<rect' in html
    assert 'Amostra · não representa totais' in html
    assert '<details class="source">' in html
    assert 'nan' not in html.lower()
    donut = Dashboard(title='Composição', widgets=[{**widgets[0], 'kind': 'donut'}])
    with pytest.raises(AgentError, match='não negativos'):
        render_html(donut, {'data': data})
    data['rows'][0]['valor'] = 5
    assert 'stroke-dasharray' in render_html(donut, {'data': data})
    data['rows'] = [{'grupo': 'Jan', 'valor': 0}]
    assert 'todos os valores são zero' in render_html(donut, {'data': data})


@pytest.mark.parametrize(('value', 'expected'), [
    (123, '123,00'), (1234, '1,23 K'), (1_250_000, '1,25 Mi'),
    (2_500_000_000, '2,5 Bi'), (3_000_000_000_000, '3 Tri'),
    (-1_250_000, '-1,25 Mi'), ('1500000.25', '1,5 Mi'),
    (999_999, '1 Mi'), (0, '0,00'),
])
def test_compact_numbers(value, expected):
    from tools.dashboards import number
    assert number(value) == expected


def test_table_abbreviates_measures_and_preserves_identifiers():
    from tools.dashboards import Dashboard, render_html
    spec = Dashboard(title='Resumo', widgets=[{'title': 'Carteira', 'kind': 'table',
        'dataset_id': 'data', 'columns': {'id': 'Documento', 'ano': 'Ano', 'valor': 'Saldo'},
        'numeric_columns': ['valor']}])
    data = {'rows': [{'id': '12345678901', 'ano': 2026, 'valor': '1500000'}], 'source': {}}
    html = render_html(spec, {'data': data})
    assert '>1,5 Mi</td>' in html
    assert '>12345678901</td>' in html
    assert '>2026</td>' in html
    assert 'data-value="1500000"' in html  # ordenação usa o valor integral


def test_agent_task_inherits_browser_profile(settings, store, client_owner_scope):
    import json
    import time
    calls = []
    async def respond(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            call = SimpleNamespace(type='function_call', name='create_dashboard',
                                   arguments=json.dumps(specification(key)), call_id='dashboard-call')
            return SimpleNamespace(output=[call], output_text='')
        return SimpleNamespace(output=[], output_text='Dashboard criado.')
    llm = SimpleNamespace(responses=SimpleNamespace(create=respond))
    with TestClient(create_app(settings, mcp=MCP(), client=llm)) as client:
        with client_owner_scope(client):
            key = postgres_dataset(store)['id']
        client.get('/')
        result = client.post('/api/runs', json={'prompt': 'Crie um dashboard', 'output_format': 'dashboard'})
        assert result.status_code == 202
        run_id = result.json()['id']
        for _ in range(100):
            run = client.get('/api/runs/' + run_id).json()
            if run['status'] not in {'running', 'queued'}:
                break
            time.sleep(.005)
        assert run['status'] == 'completed'
        item = client.get('/api/dashboards').json()['dashboards'][0]
        assert run['artifacts'][0]['url'] == '/dashboards/' + item['id']


def test_dynamic_filters_apply_before_aggregation_and_display_limit(settings, store, client_owner_scope):
    from tools.dashboards import Dashboard, render_html
    rows = [{'pa': 'A', 'produto': 'Crédito', 'valor': 10},
            {'pa': 'B', 'produto': 'Crédito', 'valor': 90},
            {'pa': 'A', 'produto': 'Crédito', 'valor': 20},
            {'pa': 'A', 'produto': 'Conta', 'valor': 5}]
    data = store.save_dataset(rows, {'kind': 'upload', 'sample_only': True})
    key = data['id']
    spec = Dashboard(title='Filtros', filters=[
        {'id': 'pa', 'label': 'PA', 'dataset_id': key, 'column': 'pa'},
        {'id': 'produto', 'label': 'Produto', 'dataset_id': key, 'column': 'produto', 'kind': 'text'}],
        widgets=[{'title': 'Saldo', 'dataset_id': key, 'kind': 'metric',
                  'value_column': 'valor', 'aggregation': 'sum', 'max_rows': 1},
                 {'title': 'Produtos', 'dataset_id': key, 'kind': 'bar',
                  'value_column': 'valor', 'label_column': 'produto', 'aggregation': 'sum'}])
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        with client_owner_scope(client):
            # A mesma fonte de teste agora pertence ao usuário que cria o dashboard.
            owned = store.save_dataset(rows, data['source'])
        key = owned['id']
        for item in spec.filters:
            item.dataset_id = key
        for item in spec.widgets:
            item.dataset_id = key
        result = client.post('/api/dashboards', json=spec.model_dump())
        assert result.status_code == 201
        url = f"/api/dashboards/{result.json()['id']}/html"
        import json
        response = client.get(url, params={'filters': json.dumps({'pa': 'A', 'produto': 'CRÉD'})})
        assert response.status_code == 200
        assert '>30,00<small>' in response.text
        assert '>90,00' not in response.text
        assert 'Amostra · não representa totais' in response.text
        assert '<option value="B">B</option>' in response.text
        assert 'value="A" selected' in response.text
        assert '>125,00<small>' in client.get(url).text
        assert 'Sem dados' in client.get(url, params={'filters': '{"pa":"inexistente"}'}).text
        for invalid in ('[]', '{', '{"desconhecido":"A"}', '{"pa":12}'):
            assert client.get(url, params={'filters': invalid}).status_code == 422
    assert data['rows'] == rows
    html = render_html(spec, {key: data}, {'produto': '<script>'})
    assert 'value="&lt;script&gt;"' in html


def test_filter_configuration_and_values_are_validated():
    from pydantic import ValidationError
    from tools.dashboards import Dashboard, render_html
    widget = {'title': 'Total', 'dataset_id': 'data', 'kind': 'metric',
              'value_column': 'valor', 'aggregation': 'sum', 'max_rows': 1}
    field = {'id': 'pa', 'label': 'PA', 'dataset_id': 'data', 'column': 'pa'}
    for filters in ([field, field], [{**field, 'dataset_id': 'other'}]):
        with pytest.raises(ValidationError):
            Dashboard(title='Teste', widgets=[widget], filters=filters)
    spec = Dashboard(title='Teste', widgets=[widget], filters=[field])
    with pytest.raises(AgentError, match='coluna do filtro'):
        render_html(spec, {'data': {'rows': [{'valor': 1}], 'source': {}}})
    with pytest.raises(AgentError, match='não numérico'):
        render_html(spec, {'data': {'rows': [{'pa': 'A', 'valor': 1},
                                            {'pa': 'A', 'valor': 'inválido'}], 'source': {}}})


@pytest.mark.parametrize(('aggregation', 'expected'), [
    ('sum', 12), ('mean', 6), ('count', 2), ('min', 4), ('max', 8)])
def test_widget_aggregation_groups_after_combined_filters(aggregation, expected):
    from tools.dashboards import Dashboard, aggregate_widget, filtered_datasets
    widget = {'title': 'Por grupo', 'dataset_id': 'data', 'kind': 'bar',
              'label_column': 'grupo', 'value_column': 'valor', 'aggregation': aggregation}
    spec = Dashboard(title='Teste', widgets=[widget], filters=[
        {'id': 'pa', 'label': 'PA', 'dataset_id': 'data', 'column': 'pa'},
        {'id': 'grupo', 'label': 'Grupo', 'dataset_id': 'data', 'column': 'grupo'}])
    data = {'rows': [{'pa': 'A', 'grupo': 'X', 'valor': v} for v in (4, 8)]
                    + [{'pa': 'B', 'grupo': 'X', 'valor': 90},
                       {'pa': 'A', 'grupo': 'Y', 'valor': 100}], 'source': {}}
    filtered = filtered_datasets(spec, {'data': data, 'other': data}, {'pa': 'A', 'grupo': 'X'})
    assert filtered['other'] is data
    assert aggregate_widget(spec.widgets[0], filtered['data'])['rows'] == [{'grupo': 'X', 'valor': expected}]
