"""Contratos declarativos do plugin de internet pública."""
from pydantic import BaseModel, ConfigDict, Field


class SearchWeb(BaseModel):
    """Pesquise na internet pública; use read_web_page para confirmar as fontes retornadas."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=2, max_length=500)
    max_results: int = Field(default=5, ge=1, le=8)


class ReadWebPage(BaseModel):
    """Leia texto de uma URL HTTP/HTTPS pública, em páginas de até 12000 caracteres."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=8, max_length=2048)
    offset: int = Field(default=0, ge=0, le=1000000)
