import pytest
from pydantic import SecretStr

from core.config import Settings
from repositories.local_store import Store


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path / 'data', docs_dir=tmp_path / 'docs',
                    openai_api_key=SecretStr('test-key'), mcp_api_key=SecretStr('test-mcp-key'),
                    max_query_rows=10)


@pytest.fixture
def store(settings):
    return Store(settings.data_dir)
