# Acesso ao PostgreSQL via `pg_mcp`

Este documento orienta agentes externos a consultar o PostgreSQL por meio do servidor MCP `pg_mcp`.

O servidor é somente leitura: as ferramentas aceitam apenas operações de consulta e não devem ser usadas para inserir, atualizar ou remover dados.

## Endpoint MCP

O transporte configurado atualmente é `streamable-http`, no caminho:

```text
http://127.0.0.1:8765/mcp
```

Esse endereço é acessível apenas localmente. Para um agente externo, publique o serviço atrás de um reverse proxy com HTTPS e autenticação. O endereço externo deverá seguir este formato:

```text
https://10.1.114.16/pg_mcp/mcp
```

O prefixo `/pg_mcp/` é configurado no Nginx e é removido ao encaminhar a
requisição; o servidor MCP recebe internamente o caminho `/mcp`. Os caminhos
`/mcp`, `/sse`, `/health` e `/docs` na raiz do HTTPS não são endpoints deste
serviço.

Não exponha diretamente a porta do MCP na internet sem TLS e controles de
rede. O servidor exige a chave configurada em `MCP_API_KEY` e, nesta
instalação, aceita clientes da rede `192.168.11.0/24`.

## Autenticação

Envie a chave em cada requisição HTTP usando um dos formatos:

```http
Authorization: Bearer <MCP_API_KEY>
```

ou:

```http
X-API-Key: <MCP_API_KEY>
```

A chave deve ter pelo menos 32 caracteres e deve ser mantida somente no
ambiente seguro do cliente e do servidor. Requisições sem chave ou com chave
inválida recebem `401 Unauthorized`.

## Fluxo recomendado

O agente deve:

1. Conectar-se ao endpoint MCP.
2. Executar `initialize`.
3. Listar as ferramentas disponíveis com `tools/list`.
4. Executar `list_databases` para descobrir os databases permitidos.
5. Escolher um database retornado, como `cora`.
6. Informar `database: "cora"` em todas as chamadas seguintes.
7. Usar `list_tables`, `describe_table` ou `query` conforme a necessidade.

O parâmetro `database` é obrigatório nas consultas. O cliente pode selecionar
o database livremente entre os valores retornados por `list_databases()` e
trocar essa seleção em cada chamada. Não se deve assumir que o database de
bootstrap configurado em `PGDATABASE` é o database correto para a consulta.

## Ferramentas disponíveis

### `list_databases`

Lista os databases aos quais o usuário MCP possui permissão `CONNECT`.

Parâmetros:

```json
{}
```

### `list_tables`

Lista tabelas e views visíveis em um schema.

Parâmetros:

```json
{
  "database": "cora",
  "schema": "public"
}
```

O campo `schema` pode ser omitido; o padrão é `public`.

### `describe_table`

Retorna colunas, tipos, nulabilidade e valores padrão de uma tabela ou view.

Parâmetros:

```json
{
  "table": "usuarios",
  "database": "cora",
  "schema": "public"
}
```

### `query`

Executa uma consulta SQL de leitura no database informado.

Parâmetros:

```json
{
  "sql": "SELECT id, nome FROM usuarios ORDER BY id LIMIT 20",
  "database": "cora",
  "max_rows": 20
}
```

Use sempre consultas explícitas, com colunas selecionadas e limites razoáveis. O servidor também aplica um limite máximo de linhas e um timeout de execução.

## Exemplo de chamada MCP

Depois de inicializar a sessão, uma chamada de ferramenta usa o método `tools/call`:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "list_tables",
    "arguments": {
      "database": "cora",
      "schema": "public"
    }
  }
}
```

Para verificar a conexão efetiva sem ler dados de negócio, o agente pode executar:

```json
{
  "name": "query",
  "arguments": {
    "sql": "SELECT current_database() AS database, current_user AS user",
    "database": "cora",
    "max_rows": 1
  }
}
```

Como o database é selecionado pelo cliente, o campo `database` do resultado
deve corresponder ao valor enviado na chamada. Por exemplo, ao enviar
`database: "cora"`, o resultado esperado é `database = cora`.

Para consultar outro database permitido, repita a chamada informando outro
valor, por exemplo:

```json
{
  "name": "query",
  "arguments": {
    "sql": "SELECT current_database() AS database",
    "database": "synap",
    "max_rows": 1
  }
}
```

## Regras de segurança

- Nunca inclua senha, certificado ou chave privada em prompts, arquivos de documentação, logs ou payloads do agente.
- Use a chave de API do servidor e transporte HTTPS para acessos externos.
- Mantenha `MCP_ALLOWED_CLIENT_NETWORKS=192.168.11.0/24` para limitar a origem
  dos clientes; o endereço é verificado pelo socket e não por
  `X-Forwarded-For`.
- Faça a rotação da chave alterando `MCP_API_KEY` e reiniciando o servidor.
- Mantenha o usuário PostgreSQL com permissões mínimas, especialmente `CONNECT`, `USAGE` e `SELECT`.
- Não tente executar `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `GRANT` ou outras operações de alteração.
- Confirme o database retornado por `list_databases` antes de consultar.
- Ao trabalhar com dados pessoais ou sensíveis, selecione somente as colunas necessárias e evite retornar dados em excesso.
- Em caso de erro de conexão, verifique endpoint, autenticação, allowlist de hosts/origens e disponibilidade do serviço antes de alterar a configuração do banco.

## Estado validado

Em 11/09/2026, foi validado acesso somente leitura à database `cora` usando o usuário `mcp_user`. O schema `public` continha 28 tabelas acessíveis.
