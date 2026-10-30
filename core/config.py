from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".config/.env", ROOT / ".env"),
        env_file_encoding="utf-8-sig", extra="ignore", populate_by_name=True,
    )
    openai_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("OPENAI_API_KEY", "OPENAI_KEY")
    )
    openai_model: str = "gpt-4.1"
    openai_verify_ssl: bool = True
    pg_mcp_url: str = "https://10.1.114.16/pg_mcp/mcp"
    mcp_verify_ssl: bool = True
    mcp_ca_bundle: Path | None = None
    mcp_api_key: SecretStr = SecretStr("")
    internet_enabled: bool = True
    internet_search_provider: Literal['openai', 'duckduckgo'] = 'openai'
    internet_search_model: str = ''
    internet_timeout_seconds: int = Field(default=25, ge=1, le=60)
    internet_max_bytes: int = Field(default=1048576, ge=16384, le=2097152)
    app_api_key: SecretStr = SecretStr("")
    app_root_path: str = Field(default='', pattern=r'^(?:/[A-Za-z0-9_~-]+)*$')
    sso_enabled: bool = False
    sso_public_key: str = ""
    sso_public_key_path: Path | None = Field(
        default=None, validation_alias=AliasChoices('SSO_PUBLIC_KEY_PATH', 'PUBLIC_KEY_PATH')
    )
    sso_expected_target: str = ""
    sso_expected_issuer: str = Field(
        default='samsite', validation_alias=AliasChoices('SSO_EXPECTED_ISSUER', 'JWT_EXPECTED_ISSUER')
    )
    sso_expected_audience: str = Field(
        default='', validation_alias=AliasChoices('SSO_EXPECTED_AUDIENCE', 'JWT_EXPECTED_AUDIENCE')
    )
    sso_auth_base_url: str = ""
    sso_exchange_secret: SecretStr = SecretStr("")
    sso_auth_ca_bundle: Path | None = None
    sso_session_seconds: int = Field(default=28800, ge=60, le=86400)
    sso_cookie_secure: bool = True
    environment: str = "production"
    environment_email: str = ""
    environment_name: str = ""
    environment_profile: str | None = None
    environment_role: str | None = None
    environment_function: str | None = None
    environment_department: str | None = None
    environment_unit_number: str | None = None
    environment_unit_name: str | None = None
    environment_photo_url: str | None = None
    allowed_databases: list[str] = []
    data_dir: Path = ROOT / "data"
    docs_dir: Path = ROOT / "docs"
    pghost: str = ""
    pgport: int = Field(default=5432, ge=1, le=65535)
    pgdatabase: str = ""
    pguser: str = ""
    pgpassword: SecretStr = SecretStr("")
    pgsslmode: Literal['verify-full', 'verify-ca'] = 'verify-full'
    pgsslrootcert: str = ""
    usage_limit_6h: int = Field(default=2000000, ge=1)
    usage_limit_week: int = Field(default=15000000, ge=1)
    max_agent_steps: int = Field(default=60, ge=1, le=60)
    max_query_rows: int = Field(default=5000, ge=1, le=50000)
    max_dataset_rows: int = Field(default=50000, ge=1, le=100000)
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    max_temporary_upload_bytes: int = Field(default=500 * 1024 * 1024, ge=1024, le=500 * 1024 * 1024)
    max_temporary_expanded_bytes: int = Field(default=2 * 1024**3, ge=1024, le=4 * 1024**3)
    max_temporary_characters: int = Field(default=500 * 1024 * 1024, ge=1024, le=1024**3)
    max_temporary_rows: int = Field(default=1048576, ge=1, le=2000000)
    max_concurrent_runs: int = Field(default=2, ge=1, le=10)
    max_pending_runs: int = Field(default=20, ge=1, le=100)
    run_timeout_seconds: int = Field(default=600, ge=10, le=3600)

    @property
    def llm_ready(self) -> bool:
        return bool(self.openai_api_key.get_secret_value())
