"""Contratos PDF verificados por leitura real do arquivo, sem IA ou banco externo."""
import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from test_agent import FakeMCP, ScriptLLM, new_run

from api.main import create_app
from core.models import AgentError
from tools.data_tools import Toolbox, definitions


def report_arguments(dataset_id):
    return {
        'title': 'Análise de crédito e provisão',
        'subtitle': 'Demonstração com dados sintéticos',
        'period': 'Janeiro a junho de 2026',
        'summary': 'Os valores são ilustrativos. Não representam uma carteira real.',
        'methodology': 'Comparação dos valores armazenados; valores negativos são preservados.',
        'conclusions': 'Confirmar as definições antes de aplicar a análise a uma base real.',
        'dataset_ids': [dataset_id],
        'sections': [{'title': 'Interpretação', 'body': 'Acentos: provisão, evolução e análise. <b>Texto literal</b>.'}],
        'charts': [
            {'dataset_id': dataset_id, 'title': 'Saldo por mês', 'x': 'mes', 'y': 'saldo', 'unit': 'R$'},
            {'dataset_id': dataset_id, 'title': 'Evolução do saldo', 'kind': 'line', 'x': 'mes', 'y': 'saldo', 'unit': 'R$'},
        ],
    }


async def test_pdf_contains_professional_content_without_technical_sources(settings, store):
    dataset = store.save_dataset([{'mes': 'Janeiro', 'saldo': '10.50'},
                                  {'mes': 'Fevereiro', 'saldo': '-2.25'},
                                  {'mes': 'Março', 'saldo': '30.00'}],
                                 {'kind': 'postgresql', 'possibly_truncated': True, 'database': 'sintetico',
                                  'table': 'tabela_tecnica_privada', 'sql': 'SELECT * FROM tabela_tecnica_privada'})
    run = new_run()
    tools = Toolbox(settings, store, FakeMCP(), run)
    result = await tools.call('create_pdf_report', report_arguments(dataset['id']))
    artifact = result['artifacts'][0]
    raw = (store.artifacts_dir / artifact['filename']).read_bytes()
    assert raw.startswith(b'%PDF-')
    reader = PdfReader(io.BytesIO(raw))
    content = '\n'.join(page.extract_text() for page in reader.pages)
    for expected in ['Resumo executivo', 'provisão', 'Evolução do saldo', 'Banco de dados interno',
                     'amostra limitada', '-2,25', 'Página 1', '<b>Texto literal</b>']:
        assert expected in content
    for internal in [dataset['id'], 'sintetico', 'tabela_tecnica_privada', 'SELECT', 'rastreabilidade', 'Prévia:']:
        assert internal not in content
    assert result['warnings'] and len(run.artifacts) == 1
    # Gráficos são desenhos vetoriais, não imagens rasterizadas.
    assert any(b' re' in page.get_contents().get_data() for page in reader.pages)
    assert store.get_dataset(dataset['id'])['rows'][0]['saldo'] == '10.50'
    assert store.get_dataset(dataset['id'])['source']['table'] == 'tabela_tecnica_privada'


@pytest.mark.parametrize('rows', [[], [{'mes': 'Jan', 'saldo': None}],
                                [{'mes': 'Jan', 'saldo': 'inválido'}],
                                [{'mes': 'Jan', 'saldo': True}],
                                [{'mes': 'Jan', 'saldo': 'inf'}],
                                [{'mes': 'Jan', 'saldo': 1}, {'mes': 'Jan', 'saldo': 2}],
                                [{'outra': 'Jan', 'saldo': 1}]])
async def test_pdf_chart_errors_do_not_create_artifact(settings, store, rows):
    dataset = store.save_dataset(rows, {'kind': 'test'})
    run = new_run()
    tools = Toolbox(settings, store, FakeMCP(), run)
    with pytest.raises(AgentError):
        await tools.call('create_pdf_report', report_arguments(dataset['id']))
    assert run.artifacts == []
    assert list(store.artifacts_dir.iterdir()) == []


async def test_pdf_skill_is_discoverable_and_schema_is_registered(settings, store):
    tools = Toolbox(settings, store, FakeMCP(), new_run())
    matches = await tools.call('search_docs', {'query': 'pdf-report'})
    assert any(item['path'] == 'pdf_report/SKILL.md' for item in matches)
    document = await tools.call('read_doc', {'path': 'pdf_report/SKILL.md'})
    assert 'create_pdf_report' in document['text']
    schema = next(item for item in definitions() if item['name'] == 'create_pdf_report')
    assert 'methodology' in schema['parameters']['required']


def test_pdf_download_mime_type(settings, client_owner_scope):
    with TestClient(create_app(settings, mcp=FakeMCP(), client=ScriptLLM([]))) as client:
        with client_owner_scope(client):
            artifact = client.app.state.store.save_artifact('synthetic-run', 'Teste PDF', 'pdf', b'%PDF-test')
        response = client.get(artifact['url'])
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/pdf'


async def test_long_report_paginates_and_repeats_footer(settings, store):
    dataset = store.save_dataset([{'mes': f'Mês {index:02}', 'saldo': index} for index in range(1, 31)], {'kind': 'test'})
    args = report_arguments(dataset['id'])
    args['sections'] = [{'title': f'Seção {i}', 'body': 'Análise de dados com acentuação. ' * 80} for i in range(5)]
    args['table_rows'] = 30
    tools = Toolbox(settings, store, FakeMCP(), new_run())
    result = await tools.call('create_pdf_report', args)
    reader = PdfReader(store.artifacts_dir / result['artifacts'][0]['filename'])
    assert len(reader.pages) >= 4
    for index, page in enumerate(reader.pages, 1):
        assert f'Página {index}' in page.extract_text()
    assert 'Exibidos 12 de 30' in '\n'.join(page.extract_text() for page in reader.pages)


async def test_reports_omit_source_rows_but_keep_lineage_for_derived_data(settings, store):
    original_source = {'kind': 'postgresql', 'database': 'cora', 'schema': 'public',
                       'table': 'tabela_tecnica_privada', 'sql': 'SELECT * FROM tabela_tecnica_privada'}
    dataset = store.save_dataset([{'campo_tecnico': 'LINHA_FONTE_NAO_PUBLICAR'}], {
        'kind': 'transformation', 'original_source': original_source, 'possibly_truncated': True,
    })
    tools = Toolbox(settings, store, FakeMCP(), new_run())
    pdf = await tools.call('create_pdf_report', {
        'title': 'Panorama da carteira', 'period': 'Outubro de 2026',
        'summary': 'Análise gerencial dos indicadores da carteira.',
        'methodology': 'Análise de uma amostra, sem extrapolação para a carteira completa.',
        'dataset_ids': [dataset['id']],
    })
    report = await tools.call('create_report', {
        'title': 'Panorama da carteira', 'body': 'Análise gerencial dos indicadores da carteira.',
        'dataset_ids': [dataset['id']],
    })
    for artifact in pdf['artifacts'] + report['artifacts']:
        path = store.artifacts_dir / artifact['filename']
        if artifact['format'] == 'pdf':
            content = '\n'.join(page.extract_text() for page in PdfReader(path).pages)
        else:
            content = path.read_text(encoding='utf-8')
        assert 'Banco de dados interno' in content
        assert 'não representam totais da população' in content
        for hidden in [dataset['id'], 'cora', 'public', 'tabela_tecnica_privada', 'SELECT',
                       'campo_tecnico', 'LINHA_FONTE_NAO_PUBLICAR', '<table']:
            assert hidden not in content
    assert store.get_dataset(dataset['id'])['source']['original_source'] == original_source


@pytest.mark.parametrize('source, expected', [
    ({'kind': 'postgresql'}, 'Banco de dados interno'),
    ({'kind': 'transformation', 'original_source': {'kind': 'xlsx_upload', 'filename': 'carteira.xlsx'}},
     'Arquivo enviado: carteira.xlsx'),
    ({'kind': 'test'}, 'Dados fornecidos para análise'),
])
def test_report_sources_describe_actual_origin(source, expected):
    from tools.report_sources import report_source

    assert report_source(source) == expected


async def test_contextual_tables_and_charts_hide_technical_names_in_all_formats(settings, store):
    dataset = store.save_dataset([
        {'mes_ref': 'Janeiro', 'saldo_op': 1234.5, 'campo_ignorado': 'VALOR_NAO_EXIBIR'},
        {'mes_ref': 'Fevereiro', 'saldo_op': 1600.0, 'campo_ignorado': 'VALOR_NAO_EXIBIR'},
    ], {'kind': 'postgresql', 'table': 'tabela_tecnica_privada', 'database': 'cora'})
    table = {'dataset_id': dataset['id'], 'title': 'Saldo da carteira por mês',
             'context': 'Comparação dos saldos mensais da carteira de crédito.',
             'columns': [{'key': 'mes_ref', 'label': 'Mês'},
                         {'key': 'saldo_op', 'label': 'Saldo da carteira', 'unit': 'R$'}],
             'max_rows': 1}
    tools = Toolbox(settings, store, FakeMCP(), new_run())
    pdf_args = report_arguments(dataset['id'])
    pdf_args['charts'] = [{'dataset_id': dataset['id'], 'title': 'Evolução mensal da carteira',
                          'context': 'Variação dos saldos no período analisado.',
                          'x': 'mes_ref', 'y': 'saldo_op', 'unit': 'R$'}]
    pdf_args['tables'] = [table]
    pdf = await tools.call('create_pdf_report', pdf_args)
    html = await tools.call('create_report', {
        'title': 'Análise da carteira', 'body': 'Comparação dos saldos mensais.',
        'dataset_ids': [dataset['id']], 'tables': [table], 'chart_x': 'mes_ref', 'chart_y': 'saldo_op',
        'chart_title': 'Evolução mensal da carteira', 'chart_context': 'Variação dos saldos no período analisado.',
        'chart_unit': 'R$',
    })
    for artifact in pdf['artifacts'] + html['artifacts']:
        path = store.artifacts_dir / artifact['filename']
        content = ('\n'.join(page.extract_text() for page in PdfReader(path).pages)
                   if artifact['format'] == 'pdf' else path.read_text(encoding='utf-8'))
        for expected in ['Saldo da carteira por mês', 'Comparação dos saldos mensais',
                         'Saldo da carteira (R$)', '1.234,50', 'Exibidos 1 de 2', 'Banco de dados interno']:
            assert expected in content
        if artifact['format'] != 'md':
            assert 'Evolução mensal da carteira' in content
            assert 'Variação dos saldos' in content
        for hidden in ['mes_ref', 'saldo_op', 'campo_ignorado', 'VALOR_NAO_EXIBIR',
                       'tabela_tecnica_privada', dataset['id']]:
            assert hidden not in content


@pytest.mark.parametrize('format', ['create_pdf_report', 'create_report'])
@pytest.mark.parametrize('invalid', ['dataset', 'column'])
async def test_contextual_table_validation_prevents_invalid_artifacts(settings, store, format, invalid):
    dataset = store.save_dataset([{'valor': 10}], {'kind': 'test'})
    table = {'dataset_id': 'inexistente' if invalid == 'dataset' else dataset['id'],
             'title': 'Indicadores', 'context': 'Valores do período analisado.',
             'columns': [{'key': 'ausente' if invalid == 'column' else 'valor', 'label': 'Valor'}]}
    args = ({'title': 'Análise', 'body': 'Resumo', 'dataset_ids': [dataset['id']]}
            if format == 'create_report' else {**report_arguments(dataset['id']), 'charts': []})
    args['tables'] = [table]
    tools = Toolbox(settings, store, FakeMCP(), new_run())
    with pytest.raises(AgentError):
        await tools.call(format, args)
    assert list(store.artifacts_dir.iterdir()) == []
