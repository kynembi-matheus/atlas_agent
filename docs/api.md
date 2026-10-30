# API

## Agendamento e subagentes

Todas as rotas abaixo exigem a autorização normal da API e o proprietário da sessão.
IDs de outro usuário retornam 404. `X-Data-Session` mantém o escopo de importações.

| Método | Rota | Contrato |
|---|---|---|
| POST | `/api/workspaces` | `{conversation_id?: UUID}` valida uma sessão existente ou reserva uma nova |
| GET | `/api/workspaces/{id}/subagents` | Lista até dois perfis e seus estados/resultados |
| GET | `/api/workspaces/{id}/context?source_run_id=UUID` | Resumo privado do contexto real da execução selecionada |
| POST | `/api/workspaces/{id}/subagents` | `{name, instructions}` cria perfil do usuário com conversa própria; terceiro retorna 409 |
| POST | `/api/workspaces/{id}/delegate` | `{subagent_id, task, source_run_id?, web_search_enabled?}` delega a auxiliar do principal com contexto |
| POST | `/api/workspaces/{id}/subagents/{subagent_id}/run` | Mesmo corpo de delegação; executa perfil do usuário em conversa própria |
| POST | `/api/workspaces/{id}/subagents/{subagent_id}/cancel` | Cancela somente a task auxiliar ativa |
| POST | `/api/workspaces/{id}/schedules` | `{title, prompt, run_at, source_run_id?, web_search_enabled?, query_ids?}` cria execução única com contexto capturado no servidor |
| GET | `/api/schedules` | Até 100 tarefas do usuário, ordenadas por data |
| POST | `/api/schedules/{id}/cancel` | Cancela somente agendamento ainda pendente |

`run_at` exige data/hora futura com fuso e é normalizado para UTC. Agendamentos temporários
retornam 409. `RunRequest.subagent_tasks` aceita até duas atribuições do mesmo contrato de
delegação. `Run.parent_run_id` identifica execuções auxiliares. Resultados principais e
agendados continuam disponíveis nos endpoints de runs e conversas existentes.

Perfis retornam `created_by` e `independent_conversation_id`. Runs pessoais retornam
`agent_profile_id` e `origin_conversation_id`; mensagens normais para a conversa própria
mantêm esse perfil automaticamente. `execution_options` e `context_snapshot` preservam
as opções e a origem capturadas. O cliente não pode anexar um snapshot arbitrário nem
selecionar a origem de outro usuário. Propostas do agente são eventos `tool_result`
com `kind=schedule_proposal`; não aparecem em `/api/schedules` antes da confirmação.

`GET /api/conversations` retorna a execução mais recente de cada conversa, em ordem decrescente de criação, sem o limite legado de 100 registros. O parâmetro opcional `limit` aceita inteiros positivos. Respeita `X-Data-Session`: inclui dados persistentes e somente as conversas temporárias da sessão atual. `/historico` serve a interface de histórico completo. A barra lateral usa `/api/workspace-sessions?limit=2` para exibir as duas sessões de origem mais recentes com seus subagentes.

A descrição completa dos schemas fica em `/docs` e `/openapi.json`. Com `SSO_ENABLED=true`, a interface, documentação e `/api/*` exigem cookie de sessão SSO. Com SSO desligado, `/api/*` exige `Authorization: Bearer <APP_API_KEY>` quando configurada. Nunca envie `OPENAI_KEY` ou `MCP_API_KEY` ao navegador ou como chave da aplicação.

Com SSO ativo, `POST /login` aceita `token` em formulário URL encoded, JSON ou Bearer;
valida JWT RS256 e cria sessão local, respondendo 303 para `/`. Também aceita `code`
e `aud` em formulário/JSON para troca backend com ScdAuth. Respostas de falha: 400
campos inválidos, 401 credencial inválida/ausente/reutilizada, 413 corpo grande,
415 formato não suportado, 429 limite de tentativas, 502 falha de troca e 503 troca
não configurada. `GET /login` retorna 405 em produção e permite sessão de desenvolvimento
somente com `ENVIRONMENT=development` e launcher `--development` simultaneamente;
`?logged_out=1` não cria sessão.
`POST /logout` revoga o cookie atual e retorna 204. Requisições de escrita com Origin
divergente do target configurado são recusadas (exceto a entrada SSO em `/login`).
Essas rotas são sempre registradas. Com SSO desligado, POST de login retorna 503;
GET pode criar sessão local se as duas condições de desenvolvimento forem satisfeitas,
mesmo sem chave pública/target. Nesse modo, páginas e API exigem sessão local.
`GET /favicon.ico` retorna 204. Consulte [operação](operations.md).

## Endpoints

| Método | Caminho | Resultado |
| --- | --- | --- |
| GET | `/health` | Saúde do processo, sem testar dependências |
| GET | `/api/status` | Modelo, presença de configuração e limites, sem segredos |
| GET | `/api/skills` | Skills locais disponíveis ao agente: identificador, nome, descrição e documento de orientação |
| POST | `/api/import-sessions` | Cria sessão temporária (201); com `X-Data-Session` encerra e apaga a anterior antes de criar outra |
| DELETE | `/api/import-sessions/current` | Encerra a sessão do header `X-Data-Session`, cancela suas execuções temporárias e remove os arquivos (204) |
| POST | `/api/imports?max_datasets=10` | Upload multipart `file` XLSX/XLS/CSV; exige sessão, infere cabeçalhos/tipos por IA e retorna uma lista de datasets temporários, um por aba |
| GET | `/api/connections/pg-mcp` | Inicializa MCP e verifica ferramentas/databases; `databases.databases` contém somente bases permitidas ao usuário; pode retornar 503 |
| GET | `/api/catalog/databases` | Databases descobertos no MCP, filtrados por `ALLOWED_DATABASES` e com permissão `USAGE` no schema `public` |
| GET | `/api/catalog/tables?database=...&schema=public` | Tabelas e views do schema, com nomes e origem |
| POST | `/api/catalog/preview` | Recebe `database`, `schema` (padrão `public`) e `table`; retorna dataset e amostra de até 10 linhas |
| POST | `/api/runs` | Enfileira execução e retorna 202 com UUIDs |
| GET | `/api/runs` | Até 100 execuções recentes, da mais nova para a mais antiga |
| GET | `/api/runs/{id}` | Estado, eventos, resposta e arquivos de uma execução |
| POST | `/api/runs/{id}/cancel` | Solicita cancelamento; preserva arquivos concluídos |
| POST | `/api/datasets/upload` | Recebe `file` multipart CSV UTF-8 e retorna dataset/prévia |
| GET | `/api/datasets/{id}` | Metadados e prévia das primeiras linhas |
| GET | `/api/artifacts` | Lista os arquivos persistentes e os arquivos da sessão temporária, quando disponível |
| GET | `/api/artifacts/{id}` | Download autenticado de arquivo gerado |

## Pedido e conversa

As respostas `Run` incluem `title`, inferido pelo agente (até 80 caracteres, vazio antes
da definição). O cliente não precisa fornecê-lo. O título é preservado entre os pedidos
de uma conversa e acompanha os endpoints de listagem, respeitando o usuário autenticado.

Histórico, execuções, datasets e artefatos são filtrados pela identidade autenticada no
servidor; não existe parâmetro para escolher outro usuário. Fora do SSO, o escopo é o
cookie de navegador. IDs de outro dono retornam 404, inclusive na continuação ou no
cancelamento. `X-Data-Session` de outro usuário retorna 410. Dados legados sem dono
permanecem armazenados, mas não aparecem na API. Estatísticas do perfil são privadas.

`POST /api/runs` aceita `web_search_enabled` (booleano, padrão `false`). Somente `true`
com `INTERNET_ENABLED=true` permite as ferramentas de pesquisa e leitura web naquela
execução. `/api/status` retorna `internet_enabled`, a disponibilidade global do plugin.
Também informa `internet_search_provider` e `internet_search_model` carregados no processo
atual, permitindo verificar a configuração após reiniciar o serviço.

`X-Data-Session: <UUID>` identifica uma sessão temporária isolada. Use o header na importação, na submissão/consulta das execuções que usam esses datasets e nos downloads de seus artefatos. O servidor retorna 410 para sessão encerrada/expirada; sem o header ou com outra sessão, dados temporários não são encontrados. Sessões sem importações ou conversas temporárias mantêm a persistência existente. A partir da importação, as novas execuções dessa sessão, incluindo perguntas seguintes, eventos, datasets derivados e artefatos ficam somente na sessão e não são gravados no SQLite. O upload legado `/api/datasets/upload` continua com seu contrato persistente; `/api/imports` é o fluxo temporário.

O upload temporário não aceita código ou schema executável: a inferência usa uma função com schema Pydantic. Envia no máximo vinte linhas iniciais por aba e 20000 caracteres no conjunto, sem armazenar a resposta no serviço Responses (`store=False`). Até dez abas e 200 colunas no conjunto, respeitando limites de bytes e linhas configurados. Estruturas inconsistentes ou pouco confiáveis são recusadas; conversões incompatíveis preservam a coluna inteira como texto com aviso. A gravação das abas é atômica para o arquivo: uma falha remove todos os Parquet criados nessa importação. Fórmulas, macros e links externos não são executados. A inferência tem timeout de 150 segundos e exige chave de IA configurada.

`/api/imports` usa `MAX_TEMPORARY_UPLOAD_BYTES`, com padrão e máximo de 524288000 bytes (500 MiB) por arquivo. `/api/status` expõe `max_temporary_upload_bytes` para o navegador. Arquivos acima do limite retornam 413 antes da inferência; arquivos exatamente no limite são permitidos no controle de tamanho. Seus limites próprios de conteúdo são `MAX_TEMPORARY_ROWS` (1048576), `MAX_TEMPORARY_CHARACTERS` (524288000) e `MAX_TEMPORARY_EXPANDED_BYTES` (2 GiB). Recusas durante o processamento incluem `X-Import-Stage` (`upload`, `read`, `inference`, `validation` ou `parquet`) para identificar a etapa, além do detalhe textual. A contagem de linhas se refere aos dados após o cabeçalho, somando as abas.

```json
{
  "prompt": "Analise a evolução mensal e gere relatório e Excel.",
  "conversation_id": null,
  "dataset_ids": []
}
```

`conversation_id` vazio cria uma conversa; reutilize o identificador retornado para perguntas seguintes. `dataset_ids` recebe até dez UUIDs já retornados pelo upload ou pelas ferramentas. Um identificador inexistente é recusado antes de enfileirar.

A resposta inicial contém `id`, `conversation_id`, `prompt`, `status`, datas, `answer`, `error`, `events` e `artifacts`. Enquanto a tarefa estiver em fila ou executando, `answer` pode estar vazio. Consulte o recurso até um estado final: `completed`, `failed` ou `cancelled`. Não interprete HTTP 202 como relatório concluído.

Eventos contêm horário, tipo e mensagem. Resultados de ferramentas incluem evidências ou prévias. Não representam o raciocínio privado do modelo. Cada arquivo inclui UUID, título, formato e `url` de download. Os arquivos são retornados mesmo quando a resposta textual não lista seus links.

## Exemplo Python

Execute com `uv run python caminho_do_cliente.py`, com a aplicação já iniciada:

```python
import os
import time
import httpx

headers = {}
if key := os.getenv("APP_API_KEY"):
    headers["Authorization"] = f"Bearer {key}"

with httpx.Client(base_url="http://127.0.0.1:8080", headers=headers, timeout=45) as client:
    with open("dados.csv", "rb") as file:
        uploaded = client.post("/api/datasets/upload", files={"file": ("dados.csv", file, "text/csv")})
    uploaded.raise_for_status()
    dataset_id = uploaded.json()["dataset_id"]

    submitted = client.post("/api/runs", json={
        "prompt": "Analise apenas o CSV anexado e gere relatório HTML e Excel.",
        "dataset_ids": [dataset_id],
    })
    submitted.raise_for_status()
    run = submitted.json()
    deadline = time.monotonic() + 900
    while run["status"] in {"queued", "running"}:
        if time.monotonic() > deadline:
            client.post(f"/api/runs/{run['id']}/cancel").raise_for_status()
            raise TimeoutError("Tempo de acompanhamento excedido")
        time.sleep(1.5)
        response = client.get(f"/api/runs/{run['id']}")
        response.raise_for_status()
        run = response.json()

    print(run["answer"] or run["error"] or run["status"])
    for artifact in run["artifacts"]:
        response = client.get(artifact["url"])
        response.raise_for_status()
        filename = f"resultado-{artifact['id']}.{artifact['format']}"
        with open(filename, "wb") as output:
            output.write(response.content)
```

## Erros

| Código | Significado |
| --- | --- |
| 401 | Chave da aplicação ausente/incorreta |
| 404 | Execução, dataset ou arquivo inexistente |
| 409 | Falta chave de IA, fila cheia, conversa ocupada ou pedido vazio |
| 410 | Sessão temporária encerrada ou expirada |
| 429 | Limite de sessões temporárias atingido |
| 504 | Timeout da inferência de estrutura por IA |
| 413 | CSV excede bytes, linhas ou colunas permitidos |
| 415 | Tipo de arquivo não suportado; use CSV |
| 422 | Contrato inválido, UUID incorreto ou CSV sem dados/UTF-8 válido |
| 503 | Diagnóstico do MCP indisponível; detalhe informa a causa quando identificável |

Falhas ocorridas após aceitar uma execução aparecem em `status=failed` e `error`; consultar a execução ainda retorna HTTP 200. Os downloads usam `Cache-Control: no-store` e conteúdo de anexo. A autenticação não é passada em query string.
## Consultas favoritas

- `GET /api/queries`: retorna `{queries: [...]}` com favoritas desta instalação.
- `POST /api/queries`: cria favorita (201).
- `PUT /api/queries/{uuid}`: substitui definição preservando UUID e data de criação.
- `DELETE /api/queries/{uuid}`: exclui definição (204; inexistente retorna 404).
- `POST /api/queries/{uuid}/execute`: executa somente leitura e retorna dataset/prévia/origem.
  Com `X-Data-Session`, o resultado fica na sessão temporária. Sem esse header, fica no store local.

POST/PUT recebem `name` (1–150 caracteres, não vazio), `description` opcional (até 2000),
`database`, `sql` (até 20000 caracteres) e `max_rows` (inteiro positivo, padrão 1000).
SQL inválido, operações de escrita e bases fora da configuração retornam 422.
A execução respeita limites globais, retorna 404 para UUID inexistente e 504 em timeout.
Todos os endpoints usam a autenticação existente. Favoritas são compartilhadas por instalação.
`POST /api/runs` também aceita `query_ids: [uuid, ...]` (máximo 10); seleções inexistentes
são rejeitadas antes de enfileirar. As definições são contexto para o agente, sem execução
automática no momento da seleção.

## Perfil e estatísticas

`GET /api/profile` retorna `name`, `identity`, `scope`, `auth_mode` (`local`, `sso` ou
`development`), `profile`, `role`, `function`, `department`, `unit_number`, `unit_name`, `photo_url`
e `usage` com totais inteiros de
`conversations`, `requests`, `completed` e `artifacts`. Usa a autenticação de `/api`.
Os campos profissionais opcionais são nulos quando ausentes. Nome/e-mail e informações
profissionais vêm da sessão autenticada, ou do ambiente no bypass de desenvolvimento;
o modo local não possui identidade individual. A contagem abrange todo o histórico
persistente da instalação, sem o limite de 100 pedidos recentes; com `X-Data-Session`,
inclui também os pedidos e arquivos apenas daquela sessão temporária. Conversas são
contadas por ID distinto, inclusive quando possuem pedidos nos dois armazenamentos.
Não retorna prompts, dados importados, credenciais, tokens ou estimativas de custo.

## Dashboards

A criação aceita `filters: [{id, label, dataset_id, column, kind}]` (até 12; `kind`
é `select` ou `text`). Cada widget pode declarar `aggregation: sum|mean|count|min|max`
(exceto tabelas). Filtros do mesmo dataset combinam-se com E antes da agregação e
do limite visual. Gráficos agregados agrupam por `label_column`; cards agregam tudo.
`GET /api/dashboards/{uuid}/html?filters=<JSON codificado>` recebe um objeto de
IDs de filtros para valores textuais (até 500 caracteres cada). Valor vazio remove
o filtro. IDs desconhecidos ou valores inválidos retornam 422; nunca alteram o SQL.

Endpoints usam a autorização global e o cookie HttpOnly `scd-dashboard-profile`, gerado
pelo servidor. Preserve o cookie entre chamadas; sem ele, inicia-se outro perfil local.
IDs de outro perfil retornam 404. Não existe identidade individual autenticada nesta instalação.

- `GET /api/dashboards`: retorna `{dashboards: [{id, title, description, created_at}], limit: 4, refresh_seconds: 60}`.
- `GET /api/dashboards/{uuid}`: metadados do dashboard do perfil atual; a página dedicada
  `/dashboards/{uuid}` usa esse endpoint para acesso direto e após recarregar.
- `POST /api/dashboards`: cria a partir de datasets existentes (201). Recebe `title`,
  `description` e `widgets` (1 a 12). Cada widget define `title`, `dataset_id`, `kind`
  (`metric`, `table`, `bar`, `line`, `donut`), `columns` (mapa campo/rótulo),
  `value_column`, `label_column`, `unit` e `max_rows` (1 a 100).
  `numeric_columns` identifica as medidas da tabela que usam notação K/Mi/Bi/Tri;
  anos e identificadores devem ficar fora dessa lista. O valor bruto é mantido para ordenação.
  Indicadores exigem uma linha agregada; rosca exige valores não negativos.
  Fontes inválidas, widgets incompatíveis e cota atingida retornam 422.
- `GET /api/dashboards/{uuid}/html`: consulta fontes atuais e retorna HTML sem cache.
  Usa `X-Data-Session` para importações. Retorna 422 para fonte expirada/incompatível,
  504 ao exceder 35 segundos. A busca das tabelas opera nas linhas retornadas do widget.
- `DELETE /api/dashboards/{uuid}`: exclui do perfil atual (204), liberando uma vaga.

`POST /api/runs` aceita `output_format: "auto" | "sites" | "dashboard"` (padrão `auto`).
A ferramenta `create_dashboard` usa o mesmo schema de criação e retorna
`{id, title, format: "dashboard", url: "/dashboards/uuid", refresh_seconds: 60}`.

`POST /api/workspaces/{conversation_id}/subagents/execute` cria um perfil com nome automático e inicia a tarefa em uma chamada. Recebe `task`, `source_run_id`, `dataset_ids`, `query_ids`, `output_format` e `web_search_enabled`. Retorna a execução (202); falhas de admissão liberam a vaga reservada.

`POST /api/workspaces/{conversation_id}/schedules/plan` recebe `prompt`, `source_run_id` e opções de execução, e retorna `title`, `steps`, `prompt` e `source_run_id`. Faz apenas uma chamada de planejamento, sem criar execução ou agendamento. Após a revisão e confirmação na interface, `POST /api/workspaces/{conversation_id}/schedules` recebe também `plan_steps`, `dataset_ids` e `output_format`. As etapas ficam persistidas para a execução futura.

`ScheduleTask` aceita `frequency` (`once`, `daily`, `weekly`), `weekdays` (0=segunda a 6=domingo) e `timezone` IANA. A regra semanal exige dias e data inicial compativel. `GET /api/schedules` lista todas as tarefas do proprietario, com `last_run_id`/`last_status` quando houver recorrencia. `GET /agendamentos` abre a pagina da biblioteca.

`GET /api/workspace-sessions?limit=2` retorna sessões agrupadas para a navegação. O limite
conta sessões de origem, incluindo todos os seus subagentes. Cada item preserva os campos
da execução principal e acrescenta `activity_at` e `subagents` (`id`, `name`, `status`,
`run_id`, `task`, `color`). A ordem considera a atividade mais recente do grupo. Se a
sessão começou por delegação, `id` é nulo até existir uma execução principal; seus
subagentes continuam acessíveis por `GET /api/runs/{run_id}`. `color` usa `teal` e
`violet` conforme a posição do perfil na sessão. Aplica o mesmo proprietário e
`X-Data-Session` das demais rotas. `/api/conversations` mantém seu contrato anterior.

## Sites estáticos

`GET /api/sites` lista os sites do perfil local e `DELETE /api/sites/{id}` exclui um site desse perfil. `GET /public/sites/{id}` disponibiliza a página sem autenticação para quem tiver o link. Os identificadores são aleatórios e a resposta é isolada por CSP sandbox. A criação é feita pela ferramenta declarativa `create_site`.

O formato `sites` permite páginas estáticas sem dataset ou dashboards com dados reais, conforme o pedido. `dashboard` permanece disponível para clientes existentes.

A interface usa `/sites` para a biblioteca e `/sites/{id}` para dashboards; os caminhos anteriores `/dashboards` permanecem disponíveis. Os endpoints de dados `/api/dashboards` permanecem inalterados.
