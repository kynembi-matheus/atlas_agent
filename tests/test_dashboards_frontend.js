'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');
function node() {
  return {value: '', hidden: false, dataset: {}, children: [], attributes: {},
    addEventListener(event, callback) { this[event] = callback; },
    setAttribute(key, value) { this.attributes[key] = value; },
    append(...children) { this.children.push(...children); },
    replaceChildren() { this.children = []; }, focus() {}};
}
function tableHarness(values) {
  const rows = values.map(([label, value]) => ({hidden: false, textContent: `${label} ${value}`,
    cells: [{dataset: {value: label}}, {dataset: {value: String(value)}}]}));
  const body = {rows: [...rows], append(row) { this.rows = this.rows.filter(item => item !== row); this.rows.push(row); }};
  const nodes = new Map(['[data-table-search]', '[data-prev]', '[data-next]', '[data-page-status]'].map(key => [key, node()]));
  const headers = [node(), node()];
  const buttons = headers.map((header, i) => ({...node(), dataset: {sort: String(i)}, closest: () => header}));
  const section = {querySelector: selector => selector === 'table' ? {querySelector: () => body} : nodes.get(selector),
    querySelectorAll: selector => selector === 'th' ? headers : buttons};
  vm.runInNewContext(read('frontend/dashboard-runtime.js'), {document: {querySelectorAll: () => [section]}});
  return {nodes, body, buttons, headers, visible: () => body.rows.filter(row => !row.hidden)};
}
test('dashboard tables sort numbers numerically in both directions and announce order', () => {
  const h = tableHarness([['A', 100], ['B', 2], ['C', -5], ['D', 11]]);
  h.buttons[1].click();
  assert.deepEqual(h.visible().map(row => Number(row.cells[1].dataset.value)), [-5, 2, 11, 100]);
  assert.equal(h.headers[1].attributes['aria-sort'], 'ascending');
  h.buttons[1].click();
  assert.deepEqual(h.visible().map(row => Number(row.cells[1].dataset.value)), [100, 11, 2, -5]);
  assert.equal(h.headers[1].attributes['aria-sort'], 'descending');
});
test('dashboard table search ignores accents and pagination follows filtered results', () => {
  const h = tableHarness(Array.from({length: 23}, (_, i) => [i === 22 ? 'Crédito <script>' : `Grupo ${i}`, i]));
  assert.equal(h.visible().length, 10);
  h.nodes.get('[data-next]').click(); h.nodes.get('[data-next]').click();
  assert.equal(h.visible().length, 3);
  assert.equal(h.nodes.get('[data-next]').disabled, true);
  const search = h.nodes.get('[data-table-search]'); search.value = 'credito'; search.input();
  assert.equal(h.visible().length, 1);
  assert.match(h.visible()[0].textContent, /<script>/);
  assert.equal(h.nodes.get('[data-prev]').disabled, true);
  search.value = 'inexistente'; search.input();
  assert.equal(h.visible().length, 0);
  assert.match(h.nodes.get('[data-page-status]').textContent, /^0 resultados/);
});
function libraryHarness(api) {
  const nodes = new Map(); const timers = [];
  const listeners = {};
  const location = {pathname: '/sites', hash: ''};
  const context = vm.createContext({$, el: node, api, setInterval: fn => timers.push(fn),
    navigatePage: p => { location.pathname = p; return context.renderDashboardPage(); }, Date,
    document: {hidden: false, addEventListener() {}},
    window: {location, confirm: () => true, addEventListener(type, listener) { listeners[type] = listener; }, history: {
      replaceState(_, __, url) { const [pathname, hash = ''] = url.split('#'); location.pathname = pathname; location.hash = `#${hash}`; }
    }}});
  function $(id) { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); }
  vm.runInContext(read('frontend/dashboards.js').replace(/^renderDashboardPage\(\);$/m, ''), context);
  return {nodes, timers, context, location, listeners};
}

test('creating a dashboard selects its output mode and preserves an existing draft', () => {
  const h = libraryHarness(async () => ({json: async () => ({dashboards: [], limit: 4})}));
  h.context.$('prompt').value = 'Minha análise';
  h.nodes.get('create-dashboard').click();
  assert.equal(h.location.pathname, '/');
  assert.equal(h.nodes.get('output-dashboard').checked, true);
  assert.equal(h.nodes.get('prompt').value, 'Minha análise');
});

test('site and dashboard actions replace only their own suggested drafts', () => {
  const h = libraryHarness(async () => ({json: async () => ({dashboards: [], limit: 4})}));
  h.nodes.get('create-dashboard').click();
  assert.match(h.nodes.get('prompt').value, /Crie um dashboard/);
  h.nodes.get('create-site').click();
  assert.match(h.nodes.get('prompt').value, /Crie um site/);
  assert.equal(h.nodes.get('output-dashboard').checked, true);
  h.nodes.get('create-dashboard').click();
  assert.match(h.nodes.get('prompt').value, /Crie um dashboard/);
  h.nodes.get('prompt').value = 'Meu texto';
  h.nodes.get('create-site').click();
  assert.equal(h.nodes.get('prompt').value, 'Meu texto');
});

test('filters accept only the current frame and persist across refresh and clear', async () => {
  const requests = [];
  const h = libraryHarness(async url => {
    requests.push(url);
    return {json: async () => ({id: 'filtered', title: 'Carteira'}), text: async () => '<html>Filtrado</html>'};
  });
  await h.context.openDashboard({id: 'filtered'});
  const frame = h.nodes.get('dashboard-frame'); frame.contentWindow = {};
  h.listeners.message({source: {}, data: {type: 'dashboard-filters', filters: {pa: 'A'}}});
  assert.equal(requests.length, 2);
  const send = filters => h.listeners.message({source: frame.contentWindow, data: {type: 'dashboard-filters', filters}});
  send({pa: 12}); assert.equal(requests.length, 2);
  send({pa: 'A & B'});
  for (let i = 0; i < 10; i++) await Promise.resolve();
  assert.deepEqual(JSON.parse(decodeURIComponent(requests.at(-1).split('filters=')[1])), {pa: 'A & B'});
  await h.context.updateDashboard();
  assert.match(requests.at(-1), /filters=/);
  send({});
  for (let i = 0; i < 10; i++) await Promise.resolve();
  assert.equal(requests.at(-1), '/api/dashboards/filtered/html');
});

test('a selection during refresh discards stale HTML and requests the latest filters', async () => {
  let resolve;
  const requests = [];
  const h = libraryHarness(async url => {
    requests.push(url);
    return {json: async () => ({id: 'x', title: 'Painel'}),
      text: () => new Promise(done => { resolve = done; })};
  });
  const opening = h.context.openDashboard({id: 'x'});
  for (let i = 0; i < 10; i++) await Promise.resolve();
  const frame = h.nodes.get('dashboard-frame'); frame.contentWindow = {};
  h.listeners.message({source: frame.contentWindow, data: {type: 'dashboard-filters', filters: {pa: 'B'}}});
  resolve('Resultado antigo'); await opening;
  for (let i = 0; i < 10; i++) await Promise.resolve();
  assert.notEqual(frame.srcdoc, 'Resultado antigo');
  assert.match(requests.at(-1), /filters=/);
  resolve('Resultado B');
  for (let i = 0; i < 10; i++) await Promise.resolve();
  assert.equal(frame.srcdoc, 'Resultado B');
});

test('filter controls send selections and reset without executing supplied code', () => {
  const form = node(), select = {...node(), value: '<script>', dataset: {dashboardFilter: 'pa'}};
  const text = {...node(), value: 'crédito', dataset: {dashboardFilter: 'busca'}};
  form.querySelectorAll = selector => selector === 'select' ? [select] : [select, text];
  const messages = [];
  vm.runInNewContext(read('frontend/dashboard-runtime.js'), {
    document: {querySelector: () => form, querySelectorAll: () => []},
    window: {parent: {postMessage: message => messages.push(message)}}
  });
  select.change();
  assert.equal(messages[0].filters.pa, '<script>');
  assert.equal(messages[0].filters.busca, 'crédito');
  let prevented = false;
  form.submit({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  form.reset();
  assert.equal(Object.keys(messages.at(-1).filters).length, 0);
});
test('library shows quota and refreshes only when visible without overlapping requests', async () => {
  let requests = 0, resolve;
  const h = libraryHarness(async url => {
    if (url === '/api/dashboards') return {json: async () => ({dashboards: Array.from({length: 4}, (_, i) => ({id: String(i), title: 'Card'})), limit: 4})};
    if (url === '/api/sites') return {json: async () => ({sites: []})};
    if (url === '/api/dashboards/0') return {json: async () => ({id: '0', title: 'Indicadores'})};
    requests++;
    return {text: () => new Promise(done => { resolve = done; })};
  });
  await h.context.loadDashboards();
  assert.equal(h.nodes.get('create-dashboard').disabled, true);
  assert.equal(h.nodes.get('dashboard-count').textContent, '4 de 4 dashboards');
  const pending = h.context.openDashboard({id: '0', title: 'Indicadores'});
  for (let i = 0; i < 6; i++) await Promise.resolve();
  await h.context.updateDashboard();
  assert.equal(requests, 1);
  resolve('<html>Atual</html>'); await pending;
  assert.equal(h.nodes.get('dashboard-frame').srcdoc, '<html>Atual</html>');
  assert.equal(h.location.pathname, '/sites/0');
  assert.equal(h.nodes.get('dashboards-page').hidden, true);
  assert.equal(h.nodes.get('dashboard-detail-page').hidden, false);
  h.context.document.hidden = true; h.timers[0]();
  assert.equal(requests, 1);
});
test('opening a dashboard by its own URL loads details without opening the library', async () => {
  const requests = [];
  const h = libraryHarness(async url => {
    requests.push(url);
    return {json: async () => ({id: 'direct', title: 'Meu painel'}), text: async () => '<html>Painel</html>'};
  });
  h.location.pathname = '/sites/direct';
  await h.context.renderDashboardPage();
  assert.deepEqual(requests, ['/api/dashboards/direct', '/api/dashboards/direct/html']);
  assert.equal(h.context.document.title, 'Meu painel · Sites · Assistente');
  assert.equal(h.nodes.get('dashboards-page').hidden, true);
  assert.equal(h.nodes.get('dashboard-frame').srcdoc, '<html>Painel</html>');
});
test('refresh failure clears the previous data instead of showing it as current', async () => {
  const h = libraryHarness(async () => { throw new Error('Fonte expirada'); });
  h.nodes.set('dashboard-frame', {...node(), srcdoc: 'Dados antigos'});
  await h.context.openDashboard({id: 'x', title: 'Teste'});
  assert.equal(h.nodes.get('dashboard-frame').srcdoc, '');
  assert.equal(h.nodes.get('dashboard-update-status').textContent, 'Fonte expirada');
});
test('dashboard shortcut is below history and frame isolates interactive scripts', () => {
  const html = read('frontend/index.html');
  assert.ok(html.indexOf('id="open-dashboards"') > html.indexOf('id="more-history"'));
  assert.ok(html.indexOf('id="open-dashboards"') < html.indexOf('id="open-profile"'));
  assert.match(html, /id="dashboard-frame"[^>]*sandbox="allow-scripts"/);
});
