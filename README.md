# Agente SCD

Assistente de dados e relatórios em linguagem natural, com **FastAPI**, interface web em português, OpenAI e PostgreSQL por meio do `pg_mcp` existente.

O agente planeja o trabalho, consulta a documentação, descobre as fontes, executa ferramentas, calcula estatísticas e gera arquivos. Cada execução preserva o andamento, os datasets e a origem das consultas. Também responde a tarefas gerais que não precisam de banco.

## Executar

Requer Python 3.11+ e [uv](https://docs.astral.sh/uv/). Na raiz do projeto:

```powershell
uv run app.py
```

O `uv` instala as dependências do `uv.lock` automaticamente na primeira execução.

- Interface: <http://127.0.0.1:8080>
- API interativa: <http://127.0.0.1:8080/docs>
- Saúde do processo: <http://127.0.0.1:8080/health>

Para desenvolvimento ou outra porta:

```powershell
uv run app.py --reload
uv run app.py --port 8081
```

Interrompa com `Ctrl+C`. Execute os comandos a partir da raiz do projeto.

## Configuração existente

A aplicação lê `.config/.env`, depois `.env`; as variáveis de ambiente do processo têm prioridade. **A configuração existente foi preservada**, incluindo `OPENAI_KEY`, `OPENAI_MODEL` e `MCP_API_KEY`. Não é preciso duplicar as chaves. `OPENAI_API_KEY` também é aceito; evite definir os dois nomes com valores diferentes.

Para uma instalação nova, copie `.env.example` para `.env` e preencha as credenciais. Não sobrescreva a configuração existente com valores vazios do exemplo.

O endpoint desta instalação é:

```dotenv
PG_MCP_URL=https://10.1.114.16/pg_mcp/mcp
MCP_VERIFY_SSL=false
```

A verificação TLS do MCP foi desativada **por solicitação do usuário**, porque o certificado interno não é reconhecido pelo ambiente. A conexão continua usando HTTPS. Em instalações com CA confiável, use `MCP_VERIFY_SSL=true` e, se necessário, `MCP_CA_BUNDLE=C:/certificados/ca.pem`. Essa opção é independente de `OPENAI_VERIFY_SSL`.

**Conexão validada nesta instalação:** o cliente descobriu os databases, executou `SELECT current_database(), 1` em `cora` e listou suas tabelas usando HTTPS e a chave existente. Um bloqueio de origem HTTP 403 ocorreu no primeiro teste e deixou de ocorrer na validação final. Se reaparecer, confira `MCP_ALLOWED_CLIENT_NETWORKS` no servidor e a origem vista pelo reverse proxy. O botão **Testar MCP** verifica a conexão. Credenciais e políticas de rede do servidor não são alteradas pela aplicação.

## Como usar

1. Abra a interface e descreva o resultado esperado, o período e os critérios.
2. Para dados locais, anexe um CSV UTF-8 com cabeçalho; vírgula e ponto e vírgula são aceitos.
3. Acompanhe o plano e as ferramentas. Expanda uma etapa para conferir as evidências.
4. Baixe os arquivos gerados. Abra o HTML baixado e use imprimir/salvar em PDF se precisar desse formato.
5. Faça uma pergunta adicional na mesma conversa para continuar a análise, ou escolha **Nova conversa**.

Exemplos:

> Explore a documentação e as tabelas disponíveis. Explique quais relatórios podem ser construídos com essas fontes.

> Prepare um relatório das vendas por equipe no último trimestre, com critérios, evolução mensal, gráfico e planilha Excel. Confirme primeiro quais colunas representam receita e data.

> Analise o CSV anexado, identifique valores ausentes e duplicados, organize os dados e gere um relatório e um CSV tratado. Preserve a base original.

> Monte um plano de indicadores para acompanhar produtividade e explique como interpretar cada um.

## Entregas disponíveis

| Recurso | Comportamento |
| --- | --- |
| Conversas e execuções | Histórico local em SQLite, acompanhamento por polling, fila e cancelamento |
| Documentação | Busca textual e leitura de `.md`, `.txt`, `.rst` e `.sql` em `docs/` e documentação do MCP |
| PostgreSQL | Descoberta de databases, tabelas e colunas; consultas SELECT pelo MCP |
| CSV | Upload limitado, dataset persistido e reutilização no contexto da conversa |
| Análise | Estatísticas, tipos, nulos, filtros, ordenação, seleção, deduplicação e agregação |
| Relatórios | Markdown e HTML com metodologia, tabelas, origem e gráfico de barras opcional |
| Exportações | CSV, Excel com aba de origem e JSON com metadados |
| Interface | Responsiva, navegação por teclado, rótulos e avisos de andamento |
| API | Contratos validados, documentação OpenAPI e autenticação opcional por Bearer |

O agente é extensível para novos relatórios sobre as fontes disponíveis. Um pedido depende da existência dos dados, da definição das métricas e das permissões do MCP. Ele não executa código arbitrário, não altera o PostgreSQL e não possui acesso irrestrito a arquivos ou serviços externos.

## Estrutura

```text
app.py                        # entrada: uv run app.py
api/main.py                   # FastAPI, endpoints, ciclo de vida e arquivos web
agents/orchestrator.py        # ciclo do agente, prompt, fila e cancelamento
core/config.py                # configuração e compatibilidade com .config/.env
core/models.py                # contratos e erros públicos
integrations/pg_mcp.py         # cliente MCP Streamable HTTP autenticado
repositories/local_store.py   # SQLite e artefatos locais
tools/data_tools.py           # ferramentas validadas de consulta, análise e exportação
frontend/                     # interface HTML/CSS/JS, sem build Node
docs/                         # arquitetura, operação e regras de negócio
skills/pg_mcp/                # material original da integração, preservado
tests/                        # testes isolados, sem chamadas externas
data/                         # criado ao executar; ignorado pelo Git
```

`skills/pg_mcp/pg_mcp.py` é um arquivo de testes fornecido com a integração; não é o servidor MCP e não precisa ser executado para iniciar esta aplicação.

## Verificar

```powershell
uv run pytest -q
uv run python -m compileall -q app.py api agents core integrations repositories tools
node --check frontend/app.js
```

Node é opcional e usado apenas para a verificação de sintaxe do JavaScript. A aplicação roda somente com `uv run app.py`.

A validação incluiu testes de SQL, limites, transformações, preservação de origem, exportações, proteção de fórmulas, escape de HTML, busca de documentos, API autenticada, ciclo do agente, cancelamento e recuperação após reinício. Um teste real com o modelo já configurado processou dados fictícios, calculou total **450** e média **150** e gerou Markdown, HTML e Excel. A conexão real com o MCP foi validada com descoberta de databases, consulta de diagnóstico e listagem de tabelas, sem leitura de dados de negócio.

## Documentação

- [Arquitetura e extensão de ferramentas](docs/architecture.md)
- [Configuração, execução e operação](docs/operations.md)
- [API e exemplos de integração](docs/api.md)
- [Contrato original do pg_mcp](skills/pg_mcp/pg_mcp_docs.md)
