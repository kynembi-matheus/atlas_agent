from pathlib import Path

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
    app_api_key: SecretStr = SecretStr("")
    allowed_databases: list[str] = []
    data_dir: Path = ROOT / "data"
    docs_dir: Path = ROOT / "docs"
    max_agent_steps: int = Field(default=20, ge=1, le=100)
    max_query_rows: int = Field(default=5000, ge=1, le=50000)
    max_dataset_rows: int = Field(default=50000, ge=1, le=100000)
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    max_concurrent_runs: int = Field(default=2, ge=1, le=10)
    max_pending_runs: int = Field(default=20, ge=1, le=100)
    run_timeout_seconds: int = Field(default=600, ge=10, le=3600)

    @property
    def llm_ready(self) -> bool:
        return bool(self.openai_api_key.get_secret_value())
