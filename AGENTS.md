# Orientações para manutenção

- Execute a aplicação pela raiz com `uv run app.py`; mantenha `app.py` como launcher.
- Organize código nos diretórios `api`, `agents`, `core`, `integrations`, `repositories` e `tools`. A interface fica em `frontend` e não precisa de build Node.
- Preserve `.config/.env`; nunca copie credenciais para código, testes, logs ou documentação.
- O MCP PostgreSQL é externo e somente leitura. O endpoint é configurável por `PG_MCP_URL`.
- A configuração `MCP_VERIFY_SSL=false` desta instalação foi autorizada pelo usuário. Não estenda essa exceção implicitamente a outros serviços.
- Novas capacidades entram como ferramentas declarativas, com schemas Pydantic e registro explícito. Não use execução arbitrária de Python/shell.
- Preserve origem de datasets e relatórios e diferencie amostras de totais.
- Valide mudanças de comportamento com testes significativos em `tests/`; esses testes não devem acessar IA ou banco reais.
- Atualize a documentação de operação e arquitetura quando contratos ou configuração mudarem.
