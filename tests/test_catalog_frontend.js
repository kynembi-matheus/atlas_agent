'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Node {
  constructor() {
    this.children = []; this.handlers = {}; this.hidden = true; this.value = ''; this.maxLength = 16000;
    this.attributes = {}; this.classes = new Set();
    this.classList = {toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name)};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function harness(apiHandler) {
  const nodes = new Map(); const notices = [];
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const el = (tag, className, text) => { const node = new Node(); node.tag = tag; node.textContent = text; return node; };
  const context = vm.createContext({$, el, api: apiHandler, URLSearchParams, notice: message => notices.push(message), document: {body: new Node()}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/catalog.js'), 'utf8'), context);
  $('preview-database').value = 'cora'; $('preview-schema').value = 'public';
  return {context, $, notices};
}
const table = {database: 'cora', schema: 'public', table: 'vendas'};
const response = data => ({json: async () => data});

test('dropping a table preserves the question and includes database, schema and table', () => {
  const {$} = harness();
  $('prompt').value = 'Compare os meses.';
  let prevented = false;
  $('prompt-form').handlers.drop({preventDefault: () => { prevented = true; }, dataTransfer: {getData: () => JSON.stringify(table)}});
  assert.equal(prevented, true);
  assert.match($('prompt').value, /^Compare os meses\.\nTabela PostgreSQL:/);
  for (const value of Object.values(table)) assert.ok($('prompt').value.includes(JSON.stringify(value)));
  assert.equal($('prompt').focused, true);
});

test('dropping invalid references or overlong text leaves the prompt intact', () => {
  const {$, notices, context} = harness();
  $('prompt').value = 'Pergunta';
  $('prompt-form').handlers.drop({preventDefault() {}, dataTransfer: {getData: () => '{'}});
  assert.equal($('prompt').value, 'Pergunta');
  assert.equal(notices.length, 1);
  $('prompt').maxLength = 12;
  context.addTableToChat(table);
  assert.equal($('prompt').value, 'Pergunta');
  assert.match(notices.at(-1), /limite/);
});

test('a table row provides drag data and an accessible Add to chat action', async () => {
  const {$, context} = harness(async () => response({tables: [{schema: 'public', table: 'vendas'}]}));
  await context.loadCatalogTables();
  const row = $('preview-tables').children[0];
  assert.equal(row.draggable, true);
  const transfer = {setData: (type, data) => { transfer[type] = data; }};
  row.handlers.dragstart({dataTransfer: transfer});
  assert.deepEqual(JSON.parse(transfer['application/x-agent-scd-table']), table);
  assert.match(transfer['text/plain'], /database="cora"/);
  const add = row.children[1].children[1];
  assert.match(add.attributes['aria-label'], /vendas/);
  add.handlers.click();
  assert.match($('prompt').value, /tabela="vendas"/);
});

test('preview renders values as text and explicitly labels the sample', async () => {
  const {$, context} = harness(async () => response({columns: ['nome'], preview: [{nome: '<script>literal</script>'}], source: {max_rows: 10}}));
  await context.showTablePreview(table);
  assert.equal($('table-preview-dialog').open, true);
  assert.match($('preview-scope').textContent, /Não representa o total/);
  const cell = $('preview-content').children[0].children[1].children[0].children[0];
  assert.equal(cell.tag, 'td');
  assert.equal(cell.textContent, '<script>literal</script>');
  assert.equal(cell.children.length, 0);
});

test('preview closes by button or Escape and discards pending results', async () => {
  let resolve;
  const {$, context} = harness(() => new Promise(done => { resolve = done; }));
  const pending = context.showTablePreview(table);
  assert.equal($('table-preview-dialog').open, true);
  assert.equal($('close-table-preview').focused, true);
  let prevented = false;
  $('table-preview-dialog').handlers.cancel({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal($('table-preview-dialog').open, false);
  resolve(response({columns: ['nome'], preview: [{nome: 'Antigo'}], source: {max_rows: 10}})); await pending;
  assert.equal($('preview-content').children.length, 0);
  assert.equal($('table-preview').hidden, true);
  const again = context.showTablePreview(table);
  $('close-table-preview').handlers.click();
  resolve(response({columns: [], preview: [], source: {max_rows: 10}})); await again;
  assert.equal($('table-preview-dialog').open, false);
});

test('empty results and errors remain inside the preview popup', async () => {
  let fail = false;
  const {$, context} = harness(async () => {
    if (fail) throw new Error('MCP indisponível');
    return response({columns: [], preview: [], source: {max_rows: 10}});
  });
  await context.showTablePreview(table);
  assert.equal($('preview-content').children[0].textContent, 'Nenhuma linha retornada.');
  fail = true; await context.showTablePreview(table);
  assert.equal($('table-preview-dialog').open, true);
  assert.equal($('preview-scope').textContent, 'MCP indisponível');
  assert.equal($('preview-content').children.length, 0);
});

test('table preview is in a labelled popup outside the Dados panel', () => {
  const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
  const panel = html.slice(html.indexOf('<aside id="data-preview"'), html.indexOf('<aside id="imports-panel"'));
  assert.match(panel, /id="preview-tables"/);
  assert.doesNotMatch(panel, /id="table-preview"/);
  const popup = html.slice(html.indexOf('<dialog id="table-preview-dialog"'));
  assert.match(popup, /aria-labelledby="preview-title"/);
  assert.match(popup, /id="preview-content"/);
});

test('changing database invalidates pending preview and catalog responses', async () => {
  const pending = [];
  const {$, context} = harness(() => new Promise(resolve => pending.push(resolve)));
  const oldPreview = context.showTablePreview(table);
  const oldTables = context.loadCatalogTables();
  $('preview-database').value = 'novo';
  const newTables = context.loadCatalogTables();
  pending[2](response({tables: [{schema: 'public', table: 'atual'}]}));
  await newTables;
  pending[1](response({tables: [{schema: 'public', table: 'antiga'}]}));
  pending[0](response({columns: ['nome'], preview: [{nome: 'antigo'}], source: {max_rows: 10}}));
  await Promise.all([oldPreview, oldTables]);
  assert.equal($('preview-tables').children[0].children[0].textContent, 'public.atual');
  assert.equal($('table-preview').hidden, true);
  assert.equal($('preview-content').children.length, 0);
});

test('catalog errors offer retry and closing restores focus', async () => {
  const {$, context} = harness(async () => { throw new Error('MCP indisponível'); });
  await context.loadCatalogDatabases();
  assert.equal($('catalog-status').textContent, 'MCP indisponível');
  assert.equal($('retry-catalog').hidden, false);
  context.setPreviewOpen(false);
  assert.equal($('data-preview').hidden, true);
  assert.equal($('toggle-preview').attributes['aria-expanded'], 'false');
  assert.equal($('toggle-preview').focused, true);
});

test('database selector displays only the six requested bases in order', async () => {
  const allowed = ['synap', 'deskflow', 'cora', 'crm_cob', 'hub', 'starcoop'];
  const {$, context} = harness(async url => response(url === '/api/catalog/databases'
    ? {databases: ['postgres', ...allowed.slice().reverse(), 'template1', 'outra_base', 'cora']}
    : {tables: []}));
  await context.loadCatalogDatabases();
  assert.deepEqual($('preview-database').children.map(option => option.value), allowed);
  assert.equal($('preview-database').value, 'synap');
});

test('database selector stays empty when the API returns only other bases', async () => {
  let requests = 0;
  const {$, context} = harness(async () => { requests++; return response({databases: ['postgres', 'template1']}); });
  await context.loadCatalogDatabases();
  assert.equal($('preview-database').children.length, 0);
  assert.equal($('preview-database').value, '');
  assert.equal(requests, 1);
  assert.match($('catalog-status').textContent, /Nenhum database permitido/);
});
