# Configuração e operação

O histórico exibe cinco conversas por página. Use “Anterior” e “Próxima” abaixo da lista; a indicação de página acompanha os resultados filtrados. Alterar a busca ou o status volta à primeira página. Os controles aparecem somente quando há mais de cinco resultados.

Em `/historico`, use a busca por texto (sem distinção de acentos ou maiúsculas) e o filtro por status para encontrar conversas. “Limpar filtros” restaura a listagem completa. “Atualizar” recarrega o histórico sem encerrar a sessão temporária; cada card abre o último pedido daquela conversa. A contagem reflete os filtros aplicados. Em falha de atualização, os resultados já carregados permanecem disponíveis.

## Iniciar

```powershell
uv run app.py
```

A aplicação roda em `127.0.0.1:8080`. A interface e a API usam a mesma origem; o navegador não recebe chaves do provedor ou do MCP. `uv run app.py --reload` ativa o recarregamento para desenvolvimento.

O launcher aceita `--host`, `--port`, `--reload` e `--development`. Para acesso pela rede, configure `APP_API_KEY`, um proxy HTTPS e a política de firewall da sua instalação; então use, por exemplo:

```powershell
uv run app.py --host 0.0.0.0 --port 8080
```

É uma aplicação para operador único ou ambiente compartilhado de confiança. A autenticação não isola o histórico, consultas, datasets ou importações por usuário. Com `SSO_ENABLED=true`, a interface e a API exigem sessão ScdAuth; `APP_API_KEY` não substitui essa sessão. Com SSO desligado, permanece a autenticação por `APP_API_KEY`: clientes HTTP ou um proxy autenticado devem fornecer `Authorization: Bearer <chave>`.

## Login JWT ScdAuth

Configure as variáveis no ambiente ou em `.config/.env`, preservando os valores existentes:

```dotenv
SSO_ENABLED=true
SSO_PUBLIC_KEY_PATH=.config/scdauth-public.pem
SSO_EXPECTED_TARGET=atlas.exemplo.interno
SSO_EXPECTED_ISSUER=samsite
ENVIRONMENT=production
SSO_COOKIE_SECURE=true
SSO_SESSION_SECONDS=28800
```

O arquivo PEM deve conter somente a chave **pública RSA** do emissor. Alternativamente,
`SSO_PUBLIC_KEY` aceita PEM inline com quebras de linha ou `\n` literais. A chave em arquivo
tem prioridade. `SSO_EXPECTED_TARGET` é exatamente o `netloc` do destino (host e porta,
quando houver), sem esquema ou caminho; não é obtido do Host enviado pelo cliente.
Se o emissor usar overrides, ajuste `SSO_EXPECTED_ISSUER` e `SSO_EXPECTED_AUDIENCE`.
Sem audience configurada, um JWT que contenha `aud` é rejeitado. Configuração SSO incompleta
impede a inicialização. Reinicie pela raiz com `uv run app.py`.

Cadastre no ScdAuth o destino HTTPS `https://atlas.exemplo.interno/login`. O receptor aceita:

- `POST /login` com formulário URL encoded `token=<JWT>`;
- `POST /login` com JSON `{"token":"<JWT>"}`;
- `POST /login` com `Authorization: Bearer <JWT>`.

O sucesso responde 303 para `/` e grava um cookie opaco HttpOnly, Secure, SameSite=Lax,
com duração de 8 horas por padrão, independente da validade curta do JWT de entrada.
Nenhum JWT é colocado no cookie. O mesmo `jti` só pode iniciar uma sessão uma vez até
expirar. Cookies antigos são revogados ao refazer login no mesmo navegador.
`POST /logout` revoga a sessão no servidor e remove o cookie. Requisições sem sessão
retornam 401, exceto login, saúde e arquivos estáticos. O perfil mostra nome e e-mail
validados; as estatísticas continuam refletindo o armazenamento compartilhado.

`GET /login` retorna 405 sem as duas condições simultâneas: `ENVIRONMENT=development`
e inicialização com `uv run app.py --development`. Somente nessa combinação,
cria sessão com `ENVIRONMENT_EMAIL`, `ENVIRONMENT_NAME`, `ENVIRONMENT_PROFILE`,
`ENVIRONMENT_ROLE` e `ENVIRONMENT_PHOTO_URL`. `GET /login?logged_out=1` apenas informa a
saída e não cria sessão; para encerrar a sessão use antes `POST /logout`.
`--reload` sozinho não libera o bypass; pode ser combinado com `--development`.
O acesso direto por `api.main:app` mantém o bypass bloqueado, mesmo com a variável de
ambiente em desenvolvimento. O bypass funciona também com `SSO_ENABLED=false`, sem
chave pública nem target: basta `ENVIRONMENT=development` e `uv run app.py --development`.
Nessa combinação, as páginas e a API exigem a sessão local criada por `/login`.
Nome e departamento aparecem na barra lateral; o e-mail fica no perfil. Após alterar `ENVIRONMENT_NAME`
ou `ENVIRONMENT_EMAIL` em `.config/.env`, reinicie a aplicação e atualize a página;
a sessão de desenvolvimento existente passa a refletir os valores carregados.
JWT via POST continua exigindo SSO configurado; sem ele, retorna 503. A rota `/login`
é sempre registrada: fora do bypass, GET retorna 405 mesmo com SSO desativado.
Em HTTP, o bypass de desenvolvimento cria cookie sem Secure para permitir a sessão
local. Em HTTPS mantém Secure, conforme `SSO_COOKIE_SECURE`. Sessões criadas pelo bypass
são recusadas quando ele está desabilitado. Em produção use HTTPS.
O proxy deve preservar a origem externa e não registrar corpos
ou cabeçalhos Authorization do login. Cookies autenticados usam a mesma origem da API.

O limite é de dez tentativas por minuto por IP e fingerprint SHA-256 do token/código,
por processo. O IP vem da conexão ASGI; configure a confiança em proxies no servidor,
sem confiar indiscriminadamente em X-Forwarded-For. Múltiplos workers têm contadores
independentes; use limitação adicional no proxy quando necessário.

O modo handoff do manual também aceita `code` e `aud` por formulário/JSON. Configure
`SSO_AUTH_BASE_URL` (HTTPS), `SSO_EXCHANGE_SECRET` e, se necessário,
`SSO_AUTH_CA_BUNDLE` com PEM/CA confiável e hostname/SAN correspondente. A troca envia
o target configurado como `aud` (distinto da audience do JWT), usa timeout de 5 segundos
e nunca herda `MCP_VERIFY_SSL=false`. Campos duplicados, token junto de code e formatos
inválidos são recusados. Este contrato recebe códigos por POST; não recebe code via query.

Sessões e fingerprints de `jti` ficam em `DATA_DIR/auth.sqlite3`; proteja o diretório e
inclua esse arquivo na política de retenção de dados pessoais e backup. As sessões
funcionam após reinício e entre workers que compartilhem o mesmo arquivo SQLite.
Para revogar todas, pare o serviço e remova somente `auth.sqlite3` antes de reiniciar.

Validação local: `uv run pytest tests/test_sso.py tests/test_profile.py`. Os testes geram
chaves RSA temporárias e simulam a troca HTTP, sem IA, PostgreSQL ou ScdAuth reais.

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
| `ALLOWED_DATABASES` | `[]` | Lista JSON; restringe ainda mais as seis bases disponíveis ao usuário; vazia permite as seis que forem descobertas pelo MCP |
| `APP_API_KEY` | vazio | Protege `/api/*` e downloads; interface e `/health` continuam disponíveis |
| `DATA_DIR` | `data` na raiz | SQLite, datasets e artefatos |
| `DOCS_DIR` | `docs` na raiz | Documentação consultável pelo agente |
| `MAX_AGENT_STEPS` | `60` | Máximo de rodadas de IA por execução (1 a 60); a última é reservada à síntese sem ferramentas |
| `MAX_QUERY_ROWS` | `5000` | Limite solicitado ao MCP por consulta |
| `MAX_DATASET_ROWS` | `50000` | Máximo de linhas/trechos por anexo; também limita consultas |
| `MAX_UPLOAD_BYTES` | `5242880` | Limite por arquivo anexado (5 MiB) |
| `MAX_TEMPORARY_UPLOAD_BYTES` | `524288000` | Limite por arquivo em Importe seus dados (500 MiB), configurável até esse máximo |
| `MAX_TEMPORARY_EXPANDED_BYTES` | `2147483648` | Limite do pacote XLSX descompactado na importação temporária (2 GiB) |
| `MAX_TEMPORARY_CHARACTERS` | `524288000` | Limite de caracteres extraídos na importação temporária |
| `MAX_TEMPORARY_ROWS` | `1048576` | Limite de linhas de dados por arquivo temporário, somando as abas |
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

A tolerância de espera por resposta é de 150 segundos na conexão com a IA e na leitura do MCP. O MCP mantém 30 segundos para conexão/envio e o diagnóstico de conexão da interface tem limite próprio de 35 segundos. O limite global `RUN_TIMEOUT_SECONDS` continua sendo aplicado à execução inteira.

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

### Anexos para análise

Use **Anexar** para selecionar PDF, XLSX, CSV, DOCX e PPTX juntos, até 10 arquivos por pedido. Cada arquivo é importado separadamente; uma falha não remove os anexos válidos. O envio do pedido aguarda a conclusão das importações. A API mantém `POST /api/datasets/upload` com um arquivo no campo multipart `file`, retornando `dataset_id`, prévia, contagem e origem; envie os IDs em `dataset_ids` ao criar a execução.

- CSV: UTF-8, delimitadores vírgula, ponto e vírgula, tabulação ou barra vertical. Mantém a inferência de tipos do pandas; códigos com zeros à esquerda devem ser preparados como texto em XLSX quando a preservação for essencial.
- XLSX: primeira linha de cada aba como cabeçalho; todas as abas, inclusive ocultas, são importadas e identificadas em colunas de origem cujos nomes constam de `source.sheet_column` e `source.row_column`. Cabeçalhos vazios ou repetidos recebem nomes únicos. Filtre a aba antes de combinar estruturas distintas. Fórmulas usam o resultado em cache salvo pelo Excel, sem recálculo; cache ausente é nulo.
- DOCX: texto e tabelas do corpo, com número do bloco. Células de tabela permanecem texto e colunas genéricas (`coluna_1`, etc.); confirme cabeçalhos e unidades antes de converter medidas.
- PPTX: texto e tabelas na ordem dos slides da apresentação, com slide, tabela e linha de origem.
- PDF: texto por página, sem OCR e sem reconstrução garantida de tabelas. Páginas sem texto são registradas e sinalizam extração incompleta; PDFs sem texto extraível ou protegidos por senha são recusados.

Imagens, gráficos, objetos incorporados e notas não são interpretados. Documentos são divididos em trechos de até 4.000 caracteres; a contagem de trechos/linhas não representa registros de negócio. A origem inclui nome, formato, hash SHA-256 e avisos de extração. O original não é retido; os dados extraídos ficam no dataset. A IA recebe prévias e pode ler o restante com `inspect_dataset` paginado. Avisos acompanham os dados derivados e relatórios.

Valem `MAX_UPLOAD_BYTES` (5 MiB por padrão) e `MAX_DATASET_ROWS` por arquivo; no máximo 200 colunas (198 colunas de entrada por aba XLSX, reservando duas para origem), 2 milhões de caracteres extraídos, 1.000 páginas/slides/abas, 5.000 entradas e 50 MiB descompactados por pacote Office. Arquivos acima desses limites são recusados, sem salvar um dataset parcial. A extração é local e não chama IA ou banco. `pypdf` é dependência de produção para leitura de PDFs.

`data/agent.sqlite3` contém pedidos, respostas, eventos e linhas dos datasets. `data/artifacts/` contém os arquivos gerados. Esses dados ficam em disco sem criptografia de aplicação; controle o acesso ao diretório e use as proteções da máquina conforme a sensibilidade dos dados.

As chaves não são registradas em eventos nem expostas ao navegador. O histórico de ferramentas pode conter SQL, critérios e prévias de dados: é informação de trabalho, com o mesmo nível de proteção dos relatórios. A IA recebe os dados necessários às ferramentas e às respostas; use apenas fontes autorizadas para o provedor configurado.

Não há expurgo automático. Para backup consistente, pare a aplicação e copie todo `DATA_DIR`. Para limpar, arquive ou remova esse diretório com o serviço parado; todos os históricos, datasets e links anteriores deixarão de funcionar. Não remova apenas o SQLite mantendo expectativa de recuperar o histórico pelos arquivos.

## Disponibilidade e limites

- Execute um único processo/worker. Há persistência, mas não fila distribuída.
- Reinício e `--reload` interrompem tarefas; o histórico marca as execuções como falhas e mantém arquivos concluídos.
- Cancelar interrompe o fluxo local. Consultas no servidor podem levar até o timeout do MCP para parar.
- Não há retomada automática, tarefas agendadas ou cache de respostas do modelo.
- Para upload exposto por proxy, configure também um limite de corpo HTTP próximo ao limite de upload, com margem para o multipart. O parser multipart processa o arquivo antes da validação de conteúdo da aplicação.
- A concorrência limita tarefas de IA; uso de CPU e memória depende de largura e tamanho dos datasets. Agregue bases grandes no banco.

## Validação

Use **Importar**, ao lado de **Dados** no container do chat, para ver os datasets importados na sessão, com contagens, tipos, ressalvas e amostras de até dez linhas. **Importar novos dados** abre um popup para selecionar XLSX, XLS ou CSV temporariamente. A IA identifica cabeçalhos, tipos e formatos numéricos/datas a partir de uma amostra limitada. Cada aba vira um dataset separado e é adicionada ao pedido automaticamente; **Usar no chat** permite reutilizá-la depois. Ao concluir sem erros, o popup fecha e o painel exibe os dados da sessão. Falhas ficam no popup e preservam importações válidas; durante a importação, o fechamento fica bloqueado para manter o progresso visível. Códigos com zeros à esquerda são mantidos como texto. Se o tipo sugerido não aceitar todos os valores, a coluna inteira permanece como texto, com aviso.

Os dados temporários ficam em `temp/import-sessions/<UUID>` na instalação padrão, em Parquet, com a origem preservada. Não são inseridos no SQLite. Conversas, eventos, resultados derivados e relatórios que usam essas importações também são temporários; baixe os arquivos que quiser manter. **Nova conversa** e a recarga da página encerram e apagam a sessão anterior da aba. O fechamento da página tenta encerrar a sessão; se houver interrupção abrupta, a limpeza por inatividade (uma hora, verificada a cada minuto) ou a próxima inicialização remove os resíduos gerenciados. Uma sessão não acessa os dados temporários de outra.

Instale as dependências com `uv sync --locked`: `pyarrow` grava/lê Parquet e `xlrd` lê XLS. O upload temporário aceita até **500 MB por arquivo** (500 MiB, 524288000 bytes), controlados por `MAX_TEMPORARY_UPLOAD_BYTES`; o painel mostra o limite e recusa arquivos maiores antes do envio, e o servidor também o valida. O fluxo temporário tem limites próprios: `MAX_TEMPORARY_ROWS` (1048576 linhas), no máximo dez abas, 200 colunas no conjunto, `MAX_TEMPORARY_CHARACTERS` (524288000 caracteres) e `MAX_TEMPORARY_EXPANDED_BYTES` (2 GiB descompactados por pacote XLSX). O XML é verificado em blocos, sem montar uma árvore completa adicional. O limite de upload não garante aceitação de conteúdo que ultrapasse esses limites estruturais; arquivos grandes ainda exigem memória e tempo de processamento proporcionais. Requer IA configurada; erros de inferência não geram importações parciais. O botão legado **Anexar** continua com a importação persistente anterior e seus próprios limites; use **Importar** para o fluxo temporário.

Se houver HTTP 422 ou 413 na importação, confira a mensagem exibida no painel. Recusas de leitura, inferência, validação ou gravação em Parquet também incluem o header `X-Import-Stage`; o log registra apenas etapa e status, sem nomes de arquivos, células ou respostas de IA. Mensagens de limites informam se o bloqueio ocorreu por tamanho descompactado, linhas, colunas ou caracteres. Alterações de configuração/código exigem recarregar ou reiniciar a aplicação pela raiz com `uv run app.py`.

Em **Skills**, estão disponíveis: **Relatórios em PDF**, **Relatórios em Excel**, **Gráficos para apresentação**, **Projeções autorregressivas**, **Encontrar padrões ocultos**, **Qualidade e consistência dos dados**, **Análise comparativa**, **Síntese executiva e plano de ação** e **Consultar dados internos**. As novas skills são descobertas automaticamente ao abrir o painel.

Relatórios gerenciais Excel usam `create_excel_report`: resumo, até seis abas com colunas de negócio, filtros, cabeçalhos fixos e gráficos editáveis. Os gráficos mostram até vinte registros; o relatório aceita até 30000 linhas distribuídas nas abas. Para simples extração completa use `export_dataset`. Gráficos para apresentações são entregues em PDF/HTML ou Excel editável; não há geração de PPTX ou imagens isoladas nesta ferramenta.

Projeções usam `forecast_series` com VAR/VECM (`statsmodels`) ou ARCH/GARCH (`arch`). Instale as dependências atualizadas com `uv sync --locked`. A ferramenta exige histórico regular, datas únicas, números finitos e amostra de treino suficiente; realiza backtest temporal de uma janela contra baseline, retorna intervalos condicionais de 95% e não troca de família automaticamente quando requisitos falham. ARCH/GARCH estimam variância/volatilidade com média constante e inovações normais. Projeção não garante resultado futuro nem representa causalidade. O histórico original e os diagnósticos ficam preservados; os avisos acompanham relatórios derivados.

`find_patterns` investiga até oito medidas com correlações de Spearman e valores atípicos por IQR, entre 20 e 50000 observações. Associações e outliers exigem validação no contexto de negócio; a ferramenta não confirma causalidade, fraude ou significância estatística dos achados.

Os botões **Dados** e **Skills** ficam alinhados à direita, dentro do container do chat. O seletor de skills mostra todas as skills locais disponíveis ao agente, com descrição e **Usar no chat**. A seleção acrescenta uma orientação ao pedido, preservando o texto já escrito. Complete a pergunta e envie normalmente. O catálogo inclui as skills em `skills/*/SKILL.md` e o guia de consulta PostgreSQL existente; não lista skills instaladas apenas no ambiente de desenvolvimento.

Em **Dados**, o campo **Base de Dados** oferece somente `synap`, `deskflow`, `cora`, `crm_cob`, `hub` e `starcoop` que forem descobertas no MCP, permitidas por `ALLOWED_DATABASES` e acessíveis no schema `public`. O campo **Schema** mantém o valor inicial `public`.

Use **Dados**, à direita do título, para escolher um database permitido e um schema (inicialmente `public`). Clique em **Preview** ao lado da tabela para visualizar até 10 linhas. A amostra não tem ordenação garantida nem representa o total da tabela. Trocar o database ou editar o schema limpa a prévia anterior. Arraste a tabela para o campo do chat, ou clique em **Adicionar ao chat**, para incluir database, schema e tabela no pedido; complete sua pergunta e envie normalmente. Nenhum dado é consultado por IA durante a navegação no painel. Em caso de falha no catálogo, use **Tentar novamente**. Em telas pequenas, o painel aparece na parte inferior; use × ou Escape para fechá-lo.

As respostas do chat exibem Markdown: `**negrito**`, `*itálico*`, títulos com `#`, listas, citações, tabelas e código entre crases. Tabelas e blocos de código largos têm rolagem horizontal. A formatação também se aplica ao abrir respostas do histórico; o texto original permanece armazenado. Não há build Node ou dependência de CDN. HTML recebido é exibido como texto.

Para gerar PDF, peça um relatório em PDF com período e critérios. O agente consulta `pdf_report/SKILL.md` e chama `create_pdf_report`. O arquivo fica disponível nos downloads da execução. ReportLab e `pypdf` são dependências de produção; `pypdfium2` é dependência de desenvolvimento para renderização local. Não é necessário navegador, Office ou Node para gerar o PDF. Para dados completos além das prévias, solicite CSV/Excel junto do relatório.

Os relatórios usam perfil profissional e descrevem o contexto de negócio dos dados, com gráficos e tabelas analíticas quando sustentados pelos dados. Cada visual tem título, contexto, rótulos de negócio e unidades. Para consultas internas, a origem aparece apenas como “Fonte: Banco de dados interno”, sem nomes técnicos, SQL, IDs ou tabelas-fontes. As prévias técnicas ficam desativadas (`table_rows=0` no PDF); tabelas analíticas usam `tables`, com colunas escolhidas e rótulos próprios. Arquivos completos são incluídos quando solicitados. Período, critérios e limites das amostras continuam visíveis. A rastreabilidade técnica permanece armazenada internamente; arquivos anexados não são atribuídos ao banco interno.

Para números recebidos como texto, peça ao agente que confirme as colunas de medidas, converta com `transform_dataset/to_numeric` e então calcule estatísticas ou agregações. A conversão aceita ponto decimal e recusa valores incompatíveis; não elimina erros silenciosamente. Preserve códigos/identificadores como texto. Totais da população devem ser agregados no SQL, principalmente quando houver aviso `possibly_truncated`; converter ou agrupar localmente não remove esse limite. Os relatórios incluem automaticamente o aviso da origem possivelmente truncada.

```powershell
uv run pytest -q
uv lock --check
uv run python -m compileall -q app.py api agents core integrations repositories tools
node --test tests/test_frontend.js
node tests/test_catalog_frontend.js
node tests/test_skills_frontend.js
node tests/test_imports_frontend.js
```

Se o isolamento do runner Node falhar com `spawn EPERM` no Windows, execute `node tests/test_frontend.js`.

Os testes automatizados usam IA e MCP simulados, sem custos ou acesso a dados de negócio. A integração real com a IA foi validada separadamente com dados sintéticos. A validação final do MCP confirmou descoberta de databases, uma consulta de diagnóstico em `cora` e listagem de tabelas. O HTTP 403 de origem encontrado inicialmente deixou de ocorrer. Não foi necessário ler dados de negócio para esse teste.


## Atalhos no chat

Digite `/` no campo de mensagem para buscar uma skill pelo nome. Digite `@` para escolher uma base permitida e depois uma tabela do schema `public`; também é possível digitar `@cora.vendas` para filtrar. Use as setas para navegar, Enter para escolher e Escape para fechar. Ctrl+Enter continua enviando o pedido. A seleção preserva o texto antes e depois do cursor e insere uma menção curta, como `/Relatórios em PDF` ou `@cora.public.vendas`. No envio, a interface expande as menções selecionadas para a orientação da skill ou a referência completa da tabela. Remover a menção do pedido também remove essa orientação do envio. Nenhuma análise é executada durante a seleção. Para outros schemas e amostras, use o painel de dados. Os catálogos são carregados sob demanda e mantidos em memória até recarregar a página. Falhas aparecem no menu; digitar novamente repete a consulta.

Valide os atalhos sem IA ou banco reais com `node tests/test_mentions_frontend.js`.


A interface usa o layout compacto aprovado: histórico à esquerda, ações **Dados**, **Importar** e **Skills** no cabeçalho, sugestões curtas e campo de mensagem em destaque. Os seletores continuam disponíveis pelos botões ou por `/` e `@`. A versão dos assets é atualizada no HTML para carregar o novo visual ao atualizar a página. Não há build Node, fontes externas ou CDN.
## Consultas favoritas

No painel **Dados**, **Preview** abre a amostra da tabela em um popup com base, schema,
nome da tabela e aviso dos limites. Feche pelo botão × ou por Escape para voltar à lista.
O popup mostra até dez linhas, sem representar o total da tabela, e exibe erros no próprio
local. Fechar descarta respostas pendentes da prévia.

Digite **?** no chat para buscar favoritas por nome, selecionar com Enter ou clique e
incluir a consulta no pedido. A seleção não executa SQL; envie a pergunta para o agente.
Abra **Queries** no topo da conversa para ver as favoritas. Clique em **Nova query** para
abrir o formulário em popup. Informe nome, base de dados, SQL somente leitura,
descrição opcional e limite de linhas; clique em **Salvar favorita**. A edição usa **Editar**
e **Salvar alterações**, também no popup; **Excluir** pede confirmação. Ao salvar, o popup
fecha e a lista é atualizada. Cancelar ou Escape fecha o editor. Salvar e editar não executam SQL.
As definições persistem no SQLite local (`favorite_queries`) entre reinícios e novas conversas.
São compartilhadas pelos usuários desta instalação, sob a mesma autenticação da aplicação.

**Executar** consulta o MCP sem depender de IA e mostra uma prévia de até 10 linhas,
contagem retornada e aviso de amostra quando houver truncamento. O limite efetivo respeita
`MAX_QUERY_ROWS` e `MAX_DATASET_ROWS`, mesmo que a favorita peça mais linhas.
**Usar resultado no agente** anexa o dataset já consultado, evitando nova execução.
**Usar no agente** seleciona a definição para uma pergunta; envie o pedido para o agente
executar ou analisar a consulta. Também é possível pedir ao agente que localize favoritas
pelo nome. Consultas são somente leitura e continuam sujeitas às bases permitidas.
Resultados executados pela interface pertencem à sessão temporária atual; salve downloads
antes de iniciar nova conversa ou recarregar. A definição favorita permanece salva.

## Perfil, uso e tema

Clique no seu nome, na navegação, para abrir **Meu perfil**. O painel mostra iniciais,
nome, e-mail, perfil de acesso e origem da sessão; os dados profissionais incluem cargo,
função, departamento e unidade/PA quando fornecidos pelo login. Campos ausentes aparecem
como “Não informado”. No bypass, configure `ENVIRONMENT_PROFILE`, `ENVIRONMENT_ROLE`,
`ENVIRONMENT_FUNCTION`, `ENVIRONMENT_DEPARTMENT`, `ENVIRONMENT_UNIT_NUMBER` e
`ENVIRONMENT_UNIT_NAME`. Reinicie após alterar o ambiente. `Atualizar perfil` relê os
dados da sessão atual; para receber alterações feitas no ScdAuth, faça novo login.

O popup também mostra as contagens de conversas, pedidos enviados, análises
concluídas e arquivos gerados. São totais do histórico compartilhado desta instalação
mais a sessão temporária atual, sem incluir sessões temporárias de outros navegadores.
As estatísticas são atualizadas ao abrir o popup ou clicar em **Atualizar perfil**.
Dados temporários saem da contagem quando a sessão é encerrada.

Ative **Tema escuro** em **Preferências**; desative para voltar ao claro. A escolha fica
salva neste navegador, vale também no histórico e sincroniza abas abertas.
Se o navegador bloquear armazenamento local, a troca vale apenas na página atual.
**Sair da sessão** aparece em sessões SSO ou de desenvolvimento, revoga o login e abre
a página de saída. Uma falha de rede mantém o painel aberto e permite tentar novamente.

## Dashboards

Na criação, peça filtros por categoria ou busca textual, indicando as dimensões
desejadas. Seletores aplicam ao mudar; buscas usam **Aplicar filtros** ou Enter.
**Limpar filtros** restaura os dados disponíveis. Seleções permanecem durante a
atualização automática da página aberta e são reiniciadas ao navegar ou recarregar.
Filtros afetam os widgets do mesmo dataset, incluindo indicadores agregados, mas
não recuperam linhas fora da consulta nem transformam amostras em totais.

O atalho **Dashboards** fica abaixo do Histórico e de **Ver mais** na sidebar.
Clique em **Criar dashboard**, selecione Dados ou importe um arquivo na conversa e
descreva os indicadores. Escolha a saída **Dashboard** ou peça esse formato no texto.
O agente prioriza cards, gráficos de barras, linhas e rosca, com tabelas complementares.
Tabelas têm busca sem acentos, ordenação por coluna e paginação de dez linhas; a busca
abrange as linhas exibidas do widget, até `max_rows`, não toda a base original.
Fontes e detalhes ficam recolhidos; o aviso de amostra permanece visível.
Valores grandes aparecem em notação compacta: K (mil), Mi (milhão), Bi (bilhão) e
Tri (trilhão), inclusive valores negativos. Cards, gráficos e medidas numéricas das
tabelas usam até duas casas decimais. Anos e identificadores permanecem integrais;
a ordenação das tabelas usa o valor original, antes da abreviação.

A biblioteca permite abrir e excluir dashboards e aceita até quatro por perfil local.
Cada dashboard abre em página própria (`/dashboards/uuid`), com link de volta à biblioteca.
A página usa toda a largura disponível ao lado da sidebar, com margens pequenas.
O botão no topo da sidebar recolhe a navegação para ícones e amplia o espaço do conteúdo.
Clique novamente para expandir. A preferência é salva no navegador e sincronizada entre abas.
Consultas e transformações são repetidas ao abrir e a cada 60 segundos enquanto a página
estiver visível. **Atualizar dados** consulta imediatamente, sem usar IA. Uma falha limpa
a visualização e mostra o erro. Não há consultas em segundo plano com a página fechada.

Importações refletem o conteúdo enviado, sem sincronização com o arquivo original.
Expiram ao encerrar a sessão ou recarregar a aplicação: importe novamente e recrie
o dashboard. Dashboards do banco continuam disponíveis entre sessões.

Esta instalação não tem contas individuais. A biblioteca usa um cookie opaco HttpOnly
de perfil do navegador (`scd-dashboard-profile`, validade de um ano). Navegadores diferentes
têm bibliotecas distintas; limpar cookies inicia outro perfil e perde o acesso anterior.
A cota é de perfil local, sem garantia de limite por conta autenticada. A autenticação
global APP_API_KEY continua válida; histórico e favoritas continuam compartilhados.
