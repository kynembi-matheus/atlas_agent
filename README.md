# Atlas Agent

**Agente Autônomo de Inteligência de Dados**

Explore dados. Descubra padrões. Antecipe decisões.

Powered by AI

Identidade visual minimalista e corporativa: azul-marinho (`#101D38`), turquesa (`#5EE0D0`), roxo (`#7C5CC4`) e branco (`#FFFFFF`), com temas claro e escuro e efeitos discretos.

Assistente de dados e relatórios em linguagem natural, com **FastAPI**, interface web em português, OpenAI e PostgreSQL por meio do `pg_mcp` existente.

O agente planeja o trabalho, consulta a documentação, descobre as fontes, executa ferramentas, calcula estatísticas e gera arquivos. Cada execução preserva o andamento, os datasets e a origem das consultas. Também responde a tarefas gerais que não precisam de banco.

O plugin de internet oferece `search_web` (busca hospedada via OpenAI) e
`read_web_page` (leitura de HTML/texto), disponíveis sem chave adicional. Ative o botão
**Pesquisar na web**, no canto inferior esquerdo do campo de mensagem, para habilitar
o acesso naquele pedido; a opção começa desligada.
O agente recebe URLs, data da consulta e avisos de leitura parcial para citar as fontes.
Exemplo: “Pesquise notícias recentes sobre cooperativismo de crédito e cite as fontes”.
Reinicie com `uv run app.py` após atualizar o código. Veja os limites e a configuração
em [operação do plugin de internet](docs/operations.md#plugin-de-internet).

Em **Escolher suas skills**, há orientações para relatórios PDF/Excel, gráficos para apresentações, projeções VAR/VECM/ARCH/GARCH, busca de padrões, qualidade dos dados, análise comparativa e síntese executiva. As ferramentas fazem cálculos reais sobre datasets existentes, preservam a origem e podem usar Python isolado no Work. Projeções incluem pressupostos, intervalos condicionais e backtest temporal; não garantem resultados futuros.

**Importe seus dados** aceita XLSX, XLS e CSV com inferência de cabeçalhos e tipos por IA. Os datasets ficam em Parquet na pasta `temp`, isolados por sessão, sem inserir o conteúdo no SQLite. Conversas e relatórios que usam essas importações também são temporários. A recarga da página preserva a sessão temporária enquanto ela estiver ativa. Nova conversa, expiração ou reinício do serviço apagam os dados temporários; baixe os arquivos que quiser guardar.

Em **Queries**, salve, edite e execute consultas favoritas somente leitura. Digite **?**
no campo de conversa para buscar uma favorita e selecioná-la com Enter ou clique;
inclua a pergunta e envie para o agente. Você também pode anexar um resultado já executado.
As definições ficam salvas nesta instalação entre conversas e reinícios.

Ao lado de **Anexar**, o atalho de agendamento parte do contexto da execução selecionada:
pedido, fontes, filtros e opções. O agente também pode propor um agendamento no chat,
para você revisar antes de ativar. A execução única é persistente e o resultado aparece em Sessões; a aplicação
precisa estar ligada para executar no horário. Tarefas vencidas durante uma parada são
processadas ao iniciar novamente, sem repetir execuções já registradas.

O atalho **Subagentes** separa a equipe controlada pelo principal dos agentes criados
por você, que têm conversa própria. Ambos recebem tarefas específicas e o contexto
selecionado, com no máximo dois perfis no total por sessão. Auxiliares delegados
compartilham o orçamento do principal; a conversa própria possui sua execução independente.
[Operação e limites](docs/operations.md#agendamentos-e-subagentes).

## Executar

Requer Python 3.11+ e [uv](https://docs.astral.sh/uv/). Na raiz do projeto:

```powershell
uv run app.py
```

O `uv` instala as dependências do `uv.lock` automaticamente na primeira execução.

O login ScdAuth por JWT é opcional (`SSO_ENABLED=true`), com recepção em `POST /login`
por formulário, JSON ou Bearer, e sessão local por cookie. Configure a chave pública,
target e issuer conforme [operação SSO](docs/operations.md#login-jwt-scdauth).
Histórico, datasets, arquivos e sessões temporárias são isolados por usuário autenticado.
Registros antigos sem proprietário ficam preservados e ocultos até atribuição explícita.
O bypass em `GET /login` exige `ENVIRONMENT=development` e execução com
`uv run app.py --development` ao mesmo tempo.

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

**Conexão validada nesta instalação:** o cliente descobriu os databases, executou `SELECT current_database(), 1` em `cora` e listou suas tabelas usando HTTPS e a chave existente. Um bloqueio de origem HTTP 403 ocorreu no primeiro teste e deixou de ocorrer na validação final. Se reaparecer, confira `MCP_ALLOWED_CLIENT_NETWORKS` no servidor e a origem vista pelo reverse proxy. O endpoint autenticado GET /api/connections/pg-mcp verifica a conexão. Credenciais e políticas de rede do servidor não são alteradas pela aplicação.

## Como usar

1. Abra a interface e descreva o resultado esperado, o período e os critérios.
2. Para dados locais, use **Anexar arquivos** e selecione até 10 arquivos PDF, XLSX, CSV UTF-8, DOCX ou PPTX. Planilhas fornecem dados tabulares; documentos fornecem texto e tabelas com localização. PDFs digitalizados exigem OCR prévio. Consulte os limites e detalhes de extração em [Operação](docs/operations.md#anexos-para-análise).
3. Acompanhe o plano e as ferramentas. Expanda uma etapa para conferir as evidências.
4. Baixe os arquivos gerados. Para PDF, peça um relatório em PDF com gráficos: o agente gera o arquivo diretamente.
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
| Documentação | Busca textual e leitura em `docs/`, documentação do MCP e skill de relatórios PDF |
| PostgreSQL | Descoberta de databases, tabelas e colunas; consultas SELECT pelo MCP |
| Anexos | Seleção múltipla de PDF, XLSX, CSV, DOCX e PPTX; datasets persistidos com origem e avisos de extração |
| Análise | Estatísticas, tipos, nulos, filtros, ordenação, seleção, deduplicação e agregação |
| Relatórios | PDF com gráficos vetoriais de barras/linhas, resumo executivo, seções, metodologia e fontes; também Markdown e HTML |
| Exportações | CSV, Excel com aba de origem e JSON com metadados |
| Interface | Responsiva, navegação por teclado, rótulos e avisos de andamento |
| API | Contratos validados, documentação OpenAPI e autenticação opcional por Bearer |

O agente é extensível para novos relatórios sobre as fontes disponíveis. Um pedido depende da existência dos dados, da definição das métricas e das permissões do MCP. O Work executa Python isolado em WASI; o agente não altera o PostgreSQL e não possui acesso irrestrito a arquivos ou serviços externos.

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
skills/pdf-report/SKILL.md     # orientação de relatórios PDF consultável pelo agente
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
- [Skill de relatórios em PDF](skills/pdf-report/SKILL.md)

Em **Agendar**, revise e confirme o plano no chat antes de configurar frequencia, dias, data e horario no popup. Acompanhe as tarefas na guia **Agendamentos** da sidebar.


O Work usa `wasi-python` e Wasmtime, instalados por `uv sync`; não requer administrador. Cada chamada recebe apenas o código e os dados informados na ferramenta, sem diretórios do servidor, variáveis do ambiente ou rede. A primeira execução pode demorar enquanto o runtime é compilado. Cada chamada usa uma instância nova. Arquivos criados diretamente em `/output` são oferecidos para download após execução bem-sucedida: até 10 arquivos e 200 MB no total, nos formatos CSV, XLSX, PDF, JSON, TXT, PNG, JPG, ZIP, DOCX, PPTX ou Markdown.
