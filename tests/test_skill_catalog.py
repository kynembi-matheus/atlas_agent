"""Skills exibidas são locais, legíveis pelo agente e não executam código."""
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from api.main import create_app
from core import skill_catalog
from core.skill_catalog import available_skills
from tools.data_tools import Toolbox


def test_catalog_lists_only_skill_documents_and_existing_pg_mcp_guide(tmp_path):
    root = tmp_path / 'skills'
    report = root / 'custom-skill'
    report.mkdir(parents=True)
    (report / 'SKILL.md').write_text('---\nname: custom-skill\ndescription: Descrição da skill.\n---\n# Análise gerencial\n', encoding='utf-8')
    pg = root / 'pg_mcp'
    pg.mkdir()
    (pg / 'pg_mcp_docs.md').write_text('# Guia MCP', encoding='utf-8')
    hidden = root / '.oculta'
    hidden.mkdir()
    (hidden / 'SKILL.md').write_text('# Oculta', encoding='utf-8')
    unregistered = root / 'scripts'
    unregistered.mkdir()
    (unregistered / 'example.py').write_text('raise RuntimeError("never execute")', encoding='utf-8')
    skills = available_skills(root)
    assert [skill['id'] for skill in skills] == ['custom-skill', 'pg_mcp']
    assert skills[0] == {'id': 'custom-skill', 'name': 'Análise gerencial',
                         'description': 'Descrição da skill.', 'document_path': 'custom_skill/SKILL.md'}
    assert skills[1]['document_path'] == 'pg_mcp/pg_mcp_docs.md'
    assert available_skills(tmp_path / 'missing') == []


async def test_new_skills_in_the_list_are_readable_by_agent(settings, store, tmp_path, monkeypatch):
    from tools import data_tools

    folder = tmp_path / 'skills' / 'custom-skill'
    folder.mkdir(parents=True)
    (folder / 'SKILL.md').write_text('# Skill de teste\nInstruções locais.', encoding='utf-8')
    monkeypatch.setattr(skill_catalog, 'ROOT', tmp_path)
    monkeypatch.setattr(data_tools, 'ROOT', tmp_path)
    skill = available_skills()[0]
    toolbox = Toolbox(settings, store, object(), None)
    result = await toolbox.call('read_doc', {'path': skill['document_path']})
    assert 'Instruções locais.' in result['text']


def test_skills_api_lists_application_skills_without_ai_or_mcp(settings):
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        response = client.get('/api/skills')
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert {skill['id'] for skill in response.json()['skills']} == {
            'pdf-report', 'pg_mcp', 'excel-report', 'presentation-charts', 'autoregressive-forecasts',
            'hidden-patterns', 'data-quality', 'comparative-analysis', 'executive-briefing', 'dashboard',
        }
        assert all(set(skill) == {'id', 'name', 'description', 'document_path'}
                   for skill in response.json()['skills'])


def test_skills_api_respects_application_auth(settings):
    settings.app_api_key = SecretStr('test-local')
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        assert client.get('/api/skills').status_code == 401
        assert client.get('/api/skills', headers={'Authorization': 'Bearer test-local'}).status_code == 200


def test_catalog_does_not_follow_skill_document_outside_root(tmp_path):
    root = tmp_path / 'skills'
    folder = root / 'outside'
    folder.mkdir(parents=True)
    outside = tmp_path / 'private.md'
    outside.write_text('# Não disponível', encoding='utf-8')
    try:
        (folder / 'SKILL.md').symlink_to(outside)
    except OSError:
        pytest.skip('Criação de links simbólicos não permitida neste ambiente.')
    assert available_skills(root) == []
