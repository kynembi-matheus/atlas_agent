'use strict';
const catalog = {tables: [], revision: 0, previewRevision: 0, loaded: false};
const tableMime = 'application/x-agent-scd-table';
const databaseOptions = ['synap', 'deskflow', 'cora', 'crm_cob', 'hub', 'starcoop'];

function tableReference(table) {
  return `Tabela PostgreSQL: database=${JSON.stringify(table.database)}, schema=${JSON.stringify(table.schema)}, tabela=${JSON.stringify(table.table)}.`;
}
function addTableToChat(table) {
  const prompt = $('prompt');
  const reference = tableReference(table);
  const next = `${prompt.value}${prompt.value ? '\n' : ''}${reference}\n`;
  if (next.length > prompt.maxLength) { notice('O pedido excede o limite de caracteres. Reduza o texto antes de adicionar a tabela.'); return; }
  prompt.value = next;
  prompt.focus();
}
function catalogStatus(message) { $('catalog-status').textContent = message; }
function clearTablePreview() {
  catalog.previewRevision++;
  $('table-preview').hidden = true;
  $('preview-content').replaceChildren();
  if ($('table-preview-dialog').open) $('table-preview-dialog').close();
}
async function showTablePreview(table) {
  const revision = ++catalog.previewRevision;
  $('table-preview').hidden = false;
  $('preview-title').textContent = `${table.database} · ${table.schema}.${table.table}`;
  $('preview-scope').textContent = 'Carregando amostra…';
  $('preview-content').replaceChildren();
  if (!$('table-preview-dialog').open) $('table-preview-dialog').showModal();
  $('close-table-preview').focus();
  try {
    const data = await (await api('/api/catalog/preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(table)})).json();
    if (revision !== catalog.previewRevision) return;
    $('preview-scope').textContent = `Amostra de ${data.preview.length} linha(s), até ${data.source.max_rows}. Não representa o total da tabela. Sem ordenação garantida.`;
    if (!data.preview.length) { $('preview-content').append(el('p', 'muted', 'Nenhuma linha retornada.')); return; }
    const grid = el('table');
    const head = el('thead'); const header = el('tr');
    data.columns.forEach(column => header.append(el('th', '', column)));
    head.append(header); grid.append(head);
    const body = el('tbody');
    data.preview.forEach(row => {
      const tr = el('tr');
      data.columns.forEach(column => {
        const value = row[column];
        tr.append(el('td', '', value === null || value === undefined ? 'NULL' : typeof value === 'object' ? JSON.stringify(value) : String(value)));
      });
      body.append(tr);
    });
    grid.append(body); $('preview-content').append(grid);
  } catch (error) {
    if (revision === catalog.previewRevision) $('preview-scope').textContent = error.message;
  }
}
function renderCatalogTables() {
  $('preview-tables').replaceChildren();
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  const query = normalize(($('catalog-search').value || '').trim());
  const tables = catalog.tables.filter(table => normalize(`${table.schema}.${table.table}`).includes(query));
  $('catalog-search-status').textContent = query ? `${tables.length} de ${catalog.tables.length} tabela(s)` : '';
  if (query && !tables.length) $('preview-tables').append(el('p', 'muted', 'Nenhuma tabela encontrada. Tente outro nome.'));
  for (const table of tables) {
    const row = el('div', 'catalog-table'); row.draggable = true;
    row.title = 'Arraste esta tabela para o campo do chat';
    row.addEventListener('dragstart', event => {
      event.dataTransfer.effectAllowed = 'copy';
      event.dataTransfer.setData(tableMime, JSON.stringify(table));
      event.dataTransfer.setData('text/plain', tableReference(table));
    });
    const name = el('span', 'catalog-table-name', `${table.schema}.${table.table}`);
    const actions = el('div', 'catalog-actions');
    const view = el('button', 'secondary', 'Preview'); view.type = 'button';
    view.setAttribute('aria-label', `Preview de ${table.schema}.${table.table}`);
    view.addEventListener('click', () => showTablePreview(table));
    const add = el('button', 'text-button', 'Adicionar ao chat'); add.type = 'button';
    add.setAttribute('aria-label', `Adicionar ${table.schema}.${table.table} ao chat`);
    add.addEventListener('click', () => addTableToChat(table));
    actions.append(view, add); row.append(name, actions); $('preview-tables').append(row);
  }
}
async function loadCatalogTables() {
  const revision = ++catalog.revision;
  clearTablePreview(); catalog.tables = []; renderCatalogTables();
  const database = $('preview-database').value;
  const schema = $('preview-schema').value.trim();
  if (!database || !schema) { catalogStatus('Selecione um database e informe um schema.'); return; }
  catalogStatus('Carregando tabelas…'); $('retry-catalog').hidden = true;
  try {
    const params = new URLSearchParams({database, schema});
    const data = await (await api(`/api/catalog/tables?${params}`)).json();
    if (revision !== catalog.revision) return;
    catalog.tables = data.tables.map(table => ({database, ...table}));
    renderCatalogTables();
    catalogStatus(catalog.tables.length ? `${catalog.tables.length} tabela(s). Arraste para o chat.` : 'Nenhuma tabela encontrada neste schema.');
  } catch (error) {
    if (revision !== catalog.revision) return;
    catalogStatus(error.message); $('retry-catalog').hidden = false;
  }
}
async function loadCatalogDatabases() {
  catalogStatus('Carregando databases…'); $('retry-catalog').hidden = true;
  try {
    const data = await (await api('/api/catalog/databases')).json();
    const databases = databaseOptions.filter(database => data.databases.includes(database));
    $('preview-database').replaceChildren();
    databases.forEach(database => {
      const option = el('option', '', database); option.value = database;
      $('preview-database').append(option);
    });
    $('preview-database').value = databases[0] || '';
    catalog.loaded = true;
    if (!databases.length) { catalogStatus('Nenhum database permitido disponível.'); $('retry-catalog').hidden = false; return; }
    await loadCatalogTables();
  } catch (error) { catalogStatus(error.message); $('retry-catalog').hidden = false; }
}
function setPreviewOpen(open) {
  if (open) {
    $('skills-panel').hidden = true;
    $('toggle-skills').setAttribute('aria-expanded', 'false');
    $('imports-panel').hidden = true;
    $('toggle-imports').setAttribute('aria-expanded', 'false');
  }
  $('data-preview').hidden = !open;
  $('toggle-preview').setAttribute('aria-expanded', String(open));
  document.body.classList.toggle('preview-open', open);
  if (open) { $('close-preview').focus(); if (!catalog.loaded) loadCatalogDatabases(); }
  else $('toggle-preview').focus();
}
$('toggle-preview').addEventListener('click', () => setPreviewOpen($('data-preview').hidden));
$('close-preview').addEventListener('click', () => setPreviewOpen(false));
$('close-table-preview').addEventListener('click', clearTablePreview);
$('table-preview-dialog').addEventListener('cancel', event => { event.preventDefault(); clearTablePreview(); });
$('data-preview').addEventListener('keydown', event => { if (event.key === 'Escape') setPreviewOpen(false); });
$('preview-database').addEventListener('change', loadCatalogTables);
$('catalog-search').addEventListener('input', renderCatalogTables);
$('schema-form').addEventListener('submit', event => { event.preventDefault(); loadCatalogTables(); });
$('preview-schema').addEventListener('input', () => {
  catalog.revision++; clearTablePreview(); catalog.tables = []; renderCatalogTables();
  catalogStatus('Clique em Carregar para consultar o schema.');
});
$('retry-catalog').addEventListener('click', () => catalog.loaded && $('preview-database').value ? loadCatalogTables() : loadCatalogDatabases());
$('prompt-form').addEventListener('dragover', event => {
  if (!Array.from(event.dataTransfer.types).includes(tableMime)) return;
  event.preventDefault(); event.dataTransfer.dropEffect = 'copy';
  $('prompt-form').classList.toggle('table-drop-target', true);
});
$('prompt-form').addEventListener('dragleave', () => $('prompt-form').classList.toggle('table-drop-target', false));
$('prompt-form').addEventListener('drop', event => {
  $('prompt-form').classList.toggle('table-drop-target', false);
  const payload = event.dataTransfer.getData(tableMime);
  if (!payload) return;
  event.preventDefault();
  try {
    const table = JSON.parse(payload);
    if (['database', 'schema', 'table'].every(key => typeof table[key] === 'string' && table[key].length > 0)) addTableToChat(table);
  } catch (_) { notice('Não foi possível adicionar a referência da tabela.'); }
});
