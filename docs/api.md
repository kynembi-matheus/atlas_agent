# API

A descrição completa dos schemas fica em `/docs` e `/openapi.json`. Todos os caminhos `/api/*` exigem `Authorization: Bearer <APP_API_KEY>` quando essa variável está preenchida. Nunca envie `OPENAI_KEY` ou `MCP_API_KEY` ao navegador ou como chave da aplicação.

## Endpoints

| Método | Caminho | Resultado |
| --- | --- | --- |
| GET | `/health` | Saúde do processo, sem testar dependências |
| GET | `/api/status` | Modelo, presença de configuração e limites, sem segredos |
| GET | `/api/connections/pg-mcp` | Inicializa MCP e verifica ferramentas/databases; pode retornar 503 |
| POST | `/api/runs` | Enfileira execução e retorna 202 com UUIDs |
| GET | `/api/runs` | Até 100 execuções recentes, da mais nova para a mais antiga |
| GET | `/api/runs/{id}` | Estado, eventos, resposta e arquivos de uma execução |
| POST | `/api/runs/{id}/cancel` | Solicita cancelamento; preserva arquivos concluídos |
| POST | `/api/datasets/upload` | Recebe `file` multipart CSV UTF-8 e retorna dataset/prévia |
| GET | `/api/datasets/{id}` | Metadados e prévia das primeiras linhas |
| GET | `/api/artifacts/{id}` | Download autenticado de arquivo gerado |

## Pedido e conversa

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
| 413 | CSV excede bytes, linhas ou colunas permitidos |
| 415 | Tipo de arquivo não suportado; use CSV |
| 422 | Contrato inválido, UUID incorreto ou CSV sem dados/UTF-8 válido |
| 503 | Diagnóstico do MCP indisponível; detalhe informa a causa quando identificável |

Falhas ocorridas após aceitar uma execução aparecem em `status=failed` e `error`; consultar a execução ainda retorna HTTP 200. Os downloads usam `Cache-Control: no-store` e conteúdo de anexo. A autenticação não é passada em query string.
