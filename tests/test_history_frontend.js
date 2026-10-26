'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../frontend/app.js'), 'utf8');

function harness(runs, path = '/') {
  const nodes = new Map(); const requests = []; const selected = [];
  const node = () => ({children: [], append(...items) { this.children.push(...items); },
    setAttribute() {}, replaceChildren() { this.children = []; }, addEventListener(event, handler) { this[event] = handler; }});
  const context = vm.createContext({
    document: {createElement: node, createElementNS: node},
    $: id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
    window: {location: {pathname: path}, history: {pushState(_, __, path) { context.window.location.pathname = path; }}},
    state: {}, statuses: {completed: 'Concluída'}, notice: message => assert.fail(message),
    api: async path => { requests.push(path); return {json: async () => runs}; },
    selectRun: run => selected.push(run),
  });
  vm.runInContext(source.slice(source.indexOf('function el('), source.indexOf('async function refreshStatus'))
    + source.slice(source.indexOf('async function refreshHistory()'), source.indexOf('function renderAttachments()')), context);
  vm.runInContext(source.slice(source.indexOf("$('history-previous').addEventListener"), source.indexOf("$('history-status').addEventListener")), context);
  return {context, nodes, requests, selected};
}

test('sidebar shows five recent conversations; paginated history opens the last conversation', async () => {
  const runs = Array.from({length: 107}, (_, id) => ({id, prompt: `<pedido ${id}>`, status: 'completed', created_at: '2026-10-26T12:00:00Z'}));
  const {context, nodes, requests, selected} = harness(runs);
  await context.refreshHistory();
  assert.equal(requests[0], '/api/conversations?limit=5');
  assert.equal(nodes.get('history').children.length, 5);
  context.navigatePage('/historico');
  await context.refreshHistory();
  assert.equal(requests[1], '/api/conversations');
  assert.equal(nodes.get('history-page').hidden, false);
  assert.equal(nodes.get('chat-page').hidden, true);
  assert.equal(nodes.get('all-history').children.length, 5);
  assert.equal(nodes.get('history-previous').disabled, true);
  assert.equal(nodes.get('history-page-label').textContent, 'Página 1 de 22');
  for (let i = 1; i < 22; i++) nodes.get('history-next').click();
  assert.equal(nodes.get('all-history').children.length, 2);
  assert.equal(nodes.get('history-next').disabled, true);
  nodes.get('all-history').children[1].click();
  assert.equal(selected[0].id, 106);
  nodes.get('history-previous').click();
  assert.equal(nodes.get('all-history').children.length, 5);
  assert.equal(nodes.get('history-page-label').textContent, 'Página 21 de 22');
  context.navigatePage('/');
  assert.equal(nodes.get('chat-page').hidden, false);
});

test('filters reset pagination and smaller refreshed results clamp the current page', async () => {
  const runs = Array.from({length: 12}, (_, id) => ({id, prompt: `Pedido ${id}`, status: 'completed', created_at: '2026-10-26T12:00:00Z'}));
  const {context, nodes} = harness(runs, '/historico');
  await context.refreshHistory();
  nodes.get('history-next').click();
  nodes.get('history-search').value = 'Pedido 1';
  context.renderHistoryResults();
  assert.equal(context.state.historyPage, 1);
  assert.equal(nodes.get('all-history').children.length, 3);
  assert.equal(nodes.get('history-pagination').hidden, true);
  nodes.get('history-search').value = '';
  context.renderHistoryResults();
  nodes.get('history-next').click(); nodes.get('history-next').click();
  context.state.historyRuns = runs.slice(0, 6);
  context.renderHistoryResults();
  assert.equal(context.state.historyPage, 2);
  assert.equal(nodes.get('all-history').children.length, 1);
  assert.equal(nodes.get('history-next').disabled, true);
});

test('empty history is explicit on both pages', async () => {
  const {context, nodes} = harness([], '/historico');
  await context.refreshHistory();
  assert.equal(nodes.get('history').children[0].textContent, 'Nenhuma conversa ainda.');
  assert.equal(nodes.get('all-history').children[0].children[1].textContent, 'Nenhuma conversa ainda.');
});

test('search ignores accents, combines with status, and preserves literal prompt text', async () => {
  const {context, nodes, requests} = harness([
    {id: 'a', prompt: 'Análise <script>literal</script>', status: 'completed', created_at: '2026-10-26T12:00:00Z'},
    {id: 'b', prompt: 'Análise mensal', status: 'failed', created_at: '2026-10-25T12:00:00Z'},
  ], '/historico');
  await context.refreshHistory();
  nodes.get('history-search').value = 'analise';
  nodes.get('history-status').value = 'completed';
  context.renderHistoryResults();
  assert.equal(nodes.get('history-count').textContent, '1 de 2 conversas');
  assert.equal(nodes.get('all-history').children[0].children[1].children[0].textContent, 'Análise <script>literal</script>');
  nodes.get('history-search').value = 'inexistente';
  context.renderHistoryResults();
  assert.equal(nodes.get('all-history').children[0].children[1].textContent, 'Nenhuma conversa encontrada');
  assert.equal(nodes.get('clear-history-filters').hidden, false);
  assert.equal(requests.length, 1);
});

test('failed refresh retains previous results and offers retry', async () => {
  const {context, nodes} = harness([], '/historico');
  await context.refreshHistory();
  const previous = nodes.get('all-history').children[0];
  context.api = async () => { throw new Error('Sem conexão.'); };
  await context.refreshHistory();
  assert.equal(nodes.get('all-history').children[0], previous);
  assert.match(nodes.get('history-feedback').textContent, /Atualizar/);
  assert.equal(nodes.get('reload-history').disabled, false);
});

test('Ver mais preserves native browser history and navigates on click', () => {
  const {context, nodes} = harness([]);
  const nativeHistory = context.window.history;
  // Classic scripts share the window global; a function named history overwrites it.
  context.window = context;
  context.history = nativeHistory;
  context.location = {pathname: '/'};
  context.addEventListener = () => {};
  vm.runInContext(source.slice(source.indexOf('async function refreshHistory()'), source.indexOf('function renderAttachments()'))
    + source.slice(source.indexOf("$('more-history').addEventListener"), source.indexOf("$('data-files').addEventListener")), context);
  assert.equal(context.history, nativeHistory);
  nodes.set('history-title', {focus() {}});
  let prevented = false;
  nodes.get('more-history').click({button: 0, preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(context.location.pathname, '/historico');
  assert.equal(nodes.get('history-page').hidden, false);
  nodes.get('back-chat').click({button: 0, preventDefault() {}});
  assert.equal(context.location.pathname, '/');
});
