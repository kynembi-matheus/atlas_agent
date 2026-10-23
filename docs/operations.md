# Configuração e operação

## Iniciar

```powershell
uv run app.py
```

A aplicação roda em `127.0.0.1:8080`. A interface e a API usam a mesma origem; o navegador não recebe chaves do provedor ou do MCP. `uv run app.py --reload` ativa o recarregamento para desenvolvimento.

O launcher aceita `--host`, `--port` e `--reload`. Para acesso pela rede, configure `APP_API_KEY`, um proxy HTTPS e a política de firewall da sua instalação; então use, por exemplo:

```powershell
uv run app.py --host 0.0.0.0 --port 8080
```

É uma aplicação para operador único ou ambiente compartilhado de confiança. A chave da aplicação controla acesso à mesma base local e não implementa contas ou isolamento entre usuários. Ao abrir a interface, preencha **Configurar acesso**. A chave fica na memória da aba e precisa ser informada novamente após recarregar.

## Variáveis

| Variável | Padrão | Uso |
| --- | --- | --- |
| `OPENAI_API_KEY` / `OPENAI_KEY` | vazio | Credencial do provedor; os dois nomes são aceitos |
| `OPENAI_MODEL` | `gpt-4.1` | Modelo com Responses API e function calling; respeita o valor existente |
| `OPENAI_VERIFY_SSL` | `true` | Verificação TLS da conexão OpenAI |
| `PG_MCP_URL` | `https://10.1.114.16/pg_mcp/mcp` | Endpoint Streamable HTTP do MCP |
| `MCP_API_KEY` | vazio | Enviada como Bearer ao servidor MCP |
| `MCP_VERIFY_SSL` | `true` | Verificação TLS do MCP; nesta instalação foi autorizado `false` |
| `MCP_CA_BUNDLE` | vazio | Caminho PEM para validar a CA interna quando a verificação estiver ativa |
| `ALLOWED_DATABASES` | `[]` | Lista JSON; vazia aceita os databases descobertos pelo MCP |
| `APP_API_KEY` | vazio | Protege `/api/*` e downloads; interface e `/health` continuam disponíveis |
| `DATA_DIR` | `data` na raiz | SQLite, datasets e artefatos |
| `DOCS_DIR` | `docs` na raiz | Documentação consultável pelo agente |
| `MAX_AGENT_STEPS` | `20` | Máximo de rodadas de IA por execução |
| `MAX_QUERY_ROWS` | `5000` | Limite solicitado ao MCP por consulta |
| `MAX_DATASET_ROWS` | `50000` | Máximo de linhas de CSV; também limita consultas |
| `MAX_UPLOAD_BYTES` | `5242880` | Limite de conteúdo do CSV (5 MiB) |
| `MAX_CONCURRENT_RUNS` | `2` | Execuções ativas simultâneas |
| `MAX_PENDING_RUNS` | `20` | Total de tarefas em andamento e aguardando |
| `RUN_TIMEOUT_SECONDS` | `600` | Timeout da execução após sair da fila |

Ordem: valores padrão < `.config/.env` < `.env` < ambiente do processo. Os caminhos relativos de `DATA_DIR`, `DOCS_DIR` e certificados são relativos ao diretório de execução. Inicie sempre a partir da raiz.

Para OpenAI com CA interna, configure `SSL_CERT_FILE` no ambiente do processo antes de iniciar. A configuração OpenAI já existente com TLS desativado é respeitada e sinalizada pela interface. Prefira CA válida quando disponível. Reinicie o serviço após mudar variáveis.

Exemplo de restrição:

```dotenv
ALLOWED_DATABASES=["cora"]
MAX_QUERY_ROWS=2000
```

## Conexão pg_mcp

A aplicação não inicia nem instala o servidor MCP. Ela inicializa uma sessão autenticada, descobre as ferramentas e chama `list_databases`, `list_tables`, `describe_table` e `query` pelo serviço existente.

Para esta implantação, utilize o caminho HTTPS completo `/pg_mcp/mcp`. `/mcp` na raiz do HTTPS é outro caminho e não deve ser assumido como equivalente. O prefixo `/pg_mcp/` é tratado pelo reverse proxy.

Diagnóstico:

| Sintoma | Ação |
| --- | --- |
| HTTP 401 | Confira `MCP_API_KEY` no cliente e servidor |
| HTTP 403 / rede não autorizada | Libere a origem vista pelo servidor em `MCP_ALLOWED_CLIENT_NETWORKS` e confira o proxy |
| Certificado não reconhecido | Informe a CA em `MCP_CA_BUNDLE`; a desativação explícita usa `MCP_VERIFY_SSL=false` |
| Timeout/conexão recusada | Confira rota, serviço, firewall, endereço e porta HTTPS |
| Tabelas não aparecem | Confira o database retornado e as permissões do usuário PostgreSQL |
| Consulta recusada | Confira SQL, schema, colunas, funções utilizadas e permissões de leitura |

O SQL local aceita somente uma consulta SELECT, incluindo CTEs e operações de conjuntos. Escritas, `SELECT INTO`, locks e funções administrativas conhecidas são recusados. As tabelas não são previamente fixadas no código; o agente inspeciona as disponíveis para cada pedido.

## Armazenamento, privacidade e backup

`data/agent.sqlite3` contém pedidos, respostas, eventos e linhas dos datasets. `data/artifacts/` contém os arquivos gerados. Esses dados ficam em disco sem criptografia de aplicação; controle o acesso ao diretório e use as proteções da máquina conforme a sensibilidade dos dados.

As chaves não são registradas em eventos nem expostas ao navegador. O histórico de ferramentas pode conter SQL, critérios e prévias de dados: é informação de trabalho, com o mesmo nível de proteção dos relatórios. A IA recebe os dados necessários às ferramentas e às respostas; use apenas fontes autorizadas para o provedor configurado.

Não há expurgo automático. Para backup consistente, pare a aplicação e copie todo `DATA_DIR`. Para limpar, arquive ou remova esse diretório com o serviço parado; todos os históricos, datasets e links anteriores deixarão de funcionar. Não remova apenas o SQLite mantendo expectativa de recuperar o histórico pelos arquivos.

## Disponibilidade e limites

- Execute um único processo/worker. Há persistência, mas não fila distribuída.
- Reinício e `--reload` interrompem tarefas; o histórico marca as execuções como falhas e mantém arquivos concluídos.
- Cancelar interrompe o fluxo local. Consultas no servidor podem levar até o timeout do MCP para parar.
- Não há retomada automática, tarefas agendadas, cache de respostas do modelo ou geração PDF nativa.
- Para upload exposto por proxy, configure também um limite de corpo HTTP próximo ao limite de upload, com margem para o multipart. O parser multipart processa o arquivo antes da validação de conteúdo da aplicação.
- A concorrência limita tarefas de IA; uso de CPU e memória depende de largura e tamanho dos datasets. Agregue bases grandes no banco.

## Validação

```powershell
uv run pytest -q
uv lock --check
uv run python -m compileall -q app.py api agents core integrations repositories tools
```

Os testes automatizados usam IA e MCP simulados, sem custos ou acesso a dados de negócio. A integração real com a IA foi validada separadamente com dados sintéticos. A validação final do MCP confirmou descoberta de databases, uma consulta de diagnóstico em `cora` e listagem de tabelas. O HTTP 403 de origem encontrado inicialmente deixou de ocorrer. Não foi necessário ler dados de negócio para esse teste.
