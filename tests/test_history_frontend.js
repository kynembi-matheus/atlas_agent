'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../frontend/app.js'), 'utf8');

function harness(runs, path = '/') {
  const nodes = new Map(); const requests = []; const selected = []; const timers = new Map(); let nextTimer = 0;
  const node = () => ({children: [], append(...items) { this.children.push(...items); },
    setAttribute() {}, replaceChildren() { this.children = []; }, addEventListener(event, handler) { this[event] = handler; }});
  const context = vm.createContext({
    document: {createElement: node, createElementNS: node},
    $: id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
    window: {location: {pathname: path}, history: {pushState(_, __, path) { context.window.location.pathname = path; }}},
    state: {}, statuses: {queued: 'Na fila', running: 'Em andamento', completed: 'Concluída', failed: 'Com falha', cancelled: 'Cancelada'}, notice: message => assert.fail(message),
    setTimeout(fn, delay) { timers.set(++nextTimer, {fn, delay}); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    api: async path => { requests.push(path); return {json: async () => runs}; },
    selectRun: run => selected.push(run),
  });
  vm.runInContext(source.slice(source.indexOf('function el('), source.indexOf('async function refreshStatus'))
    + source.slice(source.indexOf('async function refreshHistory('), source.indexOf('function renderAttachments()')), context);
  vm.runInContext(source.slice(source.indexOf("$('history-previous').addEventListener"), source.indexOf("$('history-status').addEventListener")), context);
  return {context, nodes, requests, selected, timers};
}

test('sidebar shows two recent sessions; paginated history opens the last conversation', async () => {
  const runs = Array.from({length: 107}, (_, id) => ({id, prompt: `<pedido ${id}>`, status: 'completed', created_at: '2026-10-26T12:00:00Z'}));
  const {context, nodes, requests, selected} = harness(runs);
  await context.refreshHistory();
  assert.equal(requests[0], '/api/workspace-sessions?limit=2');
  assert.equal(nodes.get('history').children.length, 2);
  context.navigatePage('/historico');
  await context.refreshHistory();
  assert.equal(requests[1], '/api/workspace-sessions');
  assert.equal(nodes.get('history-page').hidden, false);
  assert.equal(nodes.get('chat-page').hidden, true);
  assert.equal(nodes.get('all-history').children.length, 5);
  assert.equal(nodes.get('history').children.length, 2);
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

test('all sessions link replaces the sidebar refresh control in its heading', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');
  const heading = html.slice(html.indexOf('<div class="history-heading">'), html.indexOf('<nav id="history"'));
  assert.match(heading, /id="more-history"[^>]*href="\/sessoes">Ver todas as sessões/);
  assert.doesNotMatch(html, /id="refresh-history"/);
  assert.equal((html.match(/id="more-history"/g) || []).length, 1);
});

test('the two recent sidebar sessions keep every grouped subagent', async () => {
  const runs = Array.from({length: 3}, (_, id) => ({id: `main-${id}`, prompt: `Sessão ${id}`, status: 'completed',
    subagents: [{id: `agent-${id}`, run_id: `child-${id}`, name: 'Ana', status: 'completed', color: 'teal'}]}));
  const {context, nodes} = harness(runs, '/sessoes');
  await context.refreshHistory();
  const sidebar = nodes.get('history').children;
  assert.equal(sidebar.length, 4);
  assert.equal(sidebar[0].children[0].textContent, 'Sessão 0');
  assert.equal(sidebar[2].children[0].textContent, 'Sessão 1');
  assert.equal(sidebar[1].children.length, 1);
  assert.equal(sidebar[3].children.length, 1);
  assert.equal(nodes.get('all-history').children.length, 6);
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
  assert.equal(nodes.get('history').children[0].textContent, 'Nenhuma sessão ainda.');
  assert.equal(nodes.get('all-history').children[0].children[1].textContent, 'Nenhuma sessão ainda.');
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
  assert.equal(nodes.get('history-count').textContent, '1 de 2 sessões');
  assert.equal(nodes.get('all-history').children[0].children[1].children[0].textContent, 'Análise <script>literal</script>');
  nodes.get('history-search').value = 'inexistente';
  context.renderHistoryResults();
  assert.equal(nodes.get('all-history').children[0].children[1].textContent, 'Nenhuma sessão encontrada');
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

test('session status refreshes automatically until completed without rebuilding unchanged cards', async () => {
  const runs = [{id: 'a', prompt: 'Análise', status: 'running', created_at: '2026-10-26T12:00:00Z'}];
  const {context, nodes, timers} = harness(runs, '/sessoes');
  await context.refreshHistory();
  const card = nodes.get('all-history').children[0];
  assert.match(nodes.get('history').children[0].children[1].className, /status-running/);
  assert.equal(nodes.get('sessions-live').hidden, false);
  assert.equal([...timers.values()][0].delay, 4000);
  await [...timers.values()][0].fn();
  assert.equal(nodes.get('all-history').children[0], card);
  runs[0].status = 'completed';
  await [...timers.values()][0].fn();
  assert.equal(nodes.get('sessions-live').hidden, true);
  assert.match(nodes.get('history').children[0].children[1].className, /status-completed/);
  assert.equal(timers.size, 0);
});

test('background tabs do not issue automatic session requests', async () => {
  const {context, requests, timers} = harness([{id: 'a', prompt: 'Em fila', status: 'queued'}]);
  await context.refreshHistory();
  context.document.visibilityState = 'hidden';
  await [...timers.values()][0].fn();
  assert.equal(requests.length, 1);
  assert.equal(timers.size, 1);
});

test('inferred titles appear in sessions and search still matches the original question', async () => {
  const run = {id: 'a', title: 'Evolução da carteira', prompt: 'Compare os últimos seis meses',
    status: 'completed', created_at: '2026-10-26T12:00:00Z'};
  const {context, nodes} = harness([run], '/sessoes');
  await context.refreshHistory();
  assert.equal(nodes.get('history').children[0].children[0].textContent, run.title);
  assert.equal(nodes.get('all-history').children[0].children[1].children[0].textContent, run.title);
  nodes.get('history-search').value = 'seis meses'; context.renderHistoryResults();
  assert.equal(nodes.get('all-history').children.length, 1);
  nodes.get('history-search').value = 'evolucao'; context.renderHistoryResults();
  assert.equal(nodes.get('all-history').children.length, 1);
});

test('Ver mais preserves native browser history and navigates on click', () => {
  const {context, nodes} = harness([]);
  const nativeHistory = context.window.history;
  // Classic scripts share the window global; a function named history overwrites it.
  context.window = context;
  context.history = nativeHistory;
  context.location = {pathname: '/'};
  context.addEventListener = () => {};
  vm.runInContext(source.slice(source.indexOf('async function refreshHistory('), source.indexOf('function renderAttachments()'))
    + source.slice(source.indexOf("$('more-history').addEventListener"), source.indexOf("$('data-files').addEventListener")), context);
  assert.equal(context.history, nativeHistory);
  nodes.set('history-title', {focus() {}});
  let prevented = false;
  nodes.get('more-history').click({button: 0, preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(context.location.pathname, '/sessoes');
  assert.equal(nodes.get('history-page').hidden, false);
  nodes.get('back-chat').click({button: 0, preventDefault() {}});
  assert.equal(context.location.pathname, '/');
});

test('session children keep their group, identity and automatic status refresh', async () => {
  const runs = [{id: 'main', conversation_id: 'session', title: 'Carteira', prompt: 'Compare saldos', status: 'completed', created_at: '2026-10-28T12:00:00Z',
    subagents: [{id: 'profile', name: 'Ana', task: 'Validar saldos', status: 'running', run_id: 'child', color: 'teal'},
      {id: 'profile2', name: 'Bruno', task: 'Conferir risco', status: 'completed', run_id: 'child2', color: 'violet'}]}];
  const {context, nodes, timers, selected} = harness(runs, '/sessoes');
  await context.refreshHistory();
  assert.equal(nodes.get('history-count').textContent, '1 sessão · Mais recentes primeiro');
  assert.equal(nodes.get('all-history').children[1].children.length, 2);
  assert.equal(timers.size, 1);
  assert.equal(nodes.get('sessions-live').hidden, false);
  context.state.run = {id: 'child', agent_profile_id: 'profile'};
  context.renderSessionIdentity(context.state.run);
  assert.equal(nodes.get('conversation-title').textContent, 'Carteira · Ana');
  nodes.get('session-origin').onclick();
  assert.equal(selected[0].id, 'main');
  nodes.get('history-search').value = 'Bruno'; context.renderHistoryResults();
  assert.equal(nodes.get('all-history').children.length, 2);
  nodes.get('history-status').value = 'running'; nodes.get('history-search').value = 'Ana'; context.renderHistoryResults();
  assert.equal(nodes.get('history-count').textContent, '1 de 1 sessões');
});

test('opening a grouped child loads its current execution and keeps literal names', async () => {
  const runs = [{id: 'main', title: '<Carteira>', status: 'completed', prompt: '', subagents: [
    {id: 'p', name: '<Ana>', color: 'teal', run_id: 'child', status: 'completed'}]}];
  const {context, nodes, selected} = harness(runs, '/sessoes');
  await context.refreshHistory();
  const child = nodes.get('all-history').children[1].children[0];
  assert.equal(child.children[1].textContent, '<Ana>');
  context.api = async path => { assert.equal(path, '/api/runs/child'); return {json: async () => ({id: 'child', answer: 'Atual'})}; };
  await child.click();
  assert.equal(selected[0].answer, 'Atual');
});
