"""Catálogo das skills locais que o agente consegue ler, sem executar seus arquivos."""
import re
from pathlib import Path

from core.config import ROOT


def available_skills(root: Path | None = None) -> list[dict]:
    root = (root or ROOT / 'skills').resolve()
    if not root.is_dir():
        return []
    skills = []
    for folder in sorted(root.iterdir()):
        if folder.name.startswith('.') or not folder.is_dir() or not folder.resolve().is_relative_to(root):
            continue
        path = folder / 'SKILL.md'
        if not path.is_file() and folder.name == 'pg_mcp':
            path = folder / 'pg_mcp_docs.md'
        if (not path.is_file() or not path.resolve().is_relative_to(root)
                or path.stat().st_size > 1024 * 1024):
            continue
        content = path.read_text(encoding='utf-8-sig')
        heading = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        description = re.search(r'^description:\s*(.+)$', content, re.MULTILINE)
        if folder.name == 'pg_mcp':
            name = 'Consultar dados internos'
            summary = 'Explore bases e tabelas e consulte dados internos pelo PostgreSQL, em modo somente leitura.'
        else:
            name = heading.group(1).strip() if heading else folder.name
            summary = description.group(1).strip().strip('\"\'') if description else 'Skill disponível para orientar o agente nesta tarefa.'
        alias = folder.name.replace('-', '_')
        skills.append({'id': folder.name, 'name': name, 'description': summary,
                       'document_path': f'{alias}/{path.name}'})
    return skills
