'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Node {
  constructor() { this.children = []; this.handlers = {}; this.value = ''; this.hidden = true; this.attributes = {}; this.classList = {toggle() {}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.handlers.close?.(); }
  get options() { return this.children; }
}
function harness(apiHandler) {
  const nodes = new Map();
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const context = vm.createContext({$, api: apiHandler, el: (tag, cls, text) => Object.assign(new Node(), {tag, textContent: text}), historyIcon: name => Object.assign(new Node(), {tag: 'svg', name}), notice() {}, renderAttachments() {}, document: {body: new Node()}, window: {confirm: () => true}, state: {sessionId: 'session', files: []}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/chat-drag.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/queries.js'), 'utf8'), context);
  return {context, $};
}
const favorite = {id: 'uuid', name: 'Favorita', database: 'cora', sql: 'SELECT 1', max_rows: 1000};
const response = value => ({json: async () => value});

test('favorite selection preserves the question, deduplicates and clears on reset', () => {
  const {context, $} = harness();
  $('prompt').value = 'Compare os meses';
  context.chooseQuery(favorite); context.chooseQuery(favorite);
  assert.equal($('prompt').value, 'Compare os meses');
  assert.deepEqual(Array.from(context.selectedQueryIds()), ['uuid']);
  assert.equal($('query-attachments').children.length, 1);
  context.clearQueryAttachments();
  assert.equal(context.selectedQueryIds().length, 0);
  assert.equal($('query-result').hidden, true);
});

test('execution renders SQL values literally and attaches the existing dataset once', async () => {
  const calls = [];
  const {context, $} = harness(async (...args) => { calls.push(args); return response({dataset_id: 'data', columns: ['nome'], row_count: 10, preview: [{nome: '<script>alert(1)</script>'}], possibly_truncated: true}); });
  await context.executeFavorite(favorite);
  assert.match($('query-result-scope').textContent, /amostra/);
  const cell = $('query-result-content').children[0].children[1].children[0];
  assert.equal(cell.textContent, '<script>alert(1)</script>');
  assert.equal(cell.children.length, 0);
  $('query-result-use').handlers.click(); $('query-result-use').handlers.click();
  assert.equal(context.state.files.length, 1);
  assert.equal(context.state.files[0].id, 'data');
  assert.equal(calls.length, 1);
});

test('failed execution cannot reuse an old result and session rotation discards responses', async () => {
  let resolve;
  const {context, $} = harness(() => new Promise(done => { resolve = done; }));
  const pending = context.executeFavorite(favorite);
  context.state.sessionId = 'new-session'; context.clearQueryAttachments();
  resolve(response({dataset_id: 'old', preview: [], columns: []})); await pending;
  $('query-result-use').handlers.click();
  assert.equal(context.state.files.length, 0);
  assert.equal($('query-result').hidden, true);
});

test('save sends the edited definition and keeps it selected', async () => {
  const calls = [];
  const {context, $} = harness(async (url, options) => {
    if (url === '/api/connections/pg-mcp') return response({databases: {databases: ['cora']}});
    calls.push([url, options]); return response(options ? {...favorite, name: 'Atualizada'} : {queries: []});
  });
  context.chooseQuery(favorite); context.editQuery(favorite);
  $('query-name').value = 'Atualizada';
  await $('query-form').handlers.submit({preventDefault() {}});
  assert.equal(calls[0][0], '/api/queries/uuid');
  assert.equal(calls[0][1].method, 'PUT');
  assert.equal(JSON.parse(calls[0][1].body).name, 'Atualizada');
  assert.match($('query-attachments').children[0].children[1].textContent, /Atualizada/);
  assert.equal($('save-query').disabled, false);
  assert.equal($('query-dialog').open, false);
});

test('Queries shows favorites without loading the editor or database connection', async () => {
  const requests = [];
  const {context, $} = harness(async url => { requests.push(url); return response({queries: [favorite]}); });
  context.setQueriesOpen(true);
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests, ['/api/queries']);
  assert.equal($('queries-list').children.length, 1);
  assert.notEqual($('query-dialog').open, true);
});

test('New query and Edit open a modal with a clean or populated form; Cancel closes it', async () => {
  const {context, $} = harness(async () => response({databases: {databases: ['cora']}}));
  context.editQuery(favorite);
  assert.equal($('query-dialog').open, true);
  assert.equal($('query-dialog-title').textContent, 'Editar query');
  assert.equal($('query-sql').value, 'SELECT 1');
  $('cancel-query').handlers.click();
  assert.equal($('query-dialog').open, false);
  $('new-query').handlers.click();
  assert.equal($('query-dialog').open, true);
  assert.equal($('query-dialog-title').textContent, 'Nova query');
  assert.equal($('query-name').value, '');
  assert.equal($('query-sql').value, '');
  assert.equal($('query-name').focused, true);
  $('close-query-dialog').handlers.click();
  assert.equal($('query-dialog').open, false);
});

test('save failures stay inside the popup and preserve entered SQL', async () => {
  const {context, $} = harness(async (url, options) => {
    if (options) throw new Error('SQL inválido');
    return response({databases: {databases: ['cora']}});
  });
  context.editQuery(favorite);
  await $('query-form').handlers.submit({preventDefault() {}});
  assert.equal($('query-dialog').open, true);
  assert.equal($('query-form-status').textContent, 'SQL inválido');
  assert.equal($('query-sql').value, 'SELECT 1');
  assert.equal($('save-query').disabled, false);
});

test('query form is in a labelled native dialog outside the favorites panel', () => {
  const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
  const panel = html.slice(html.indexOf('<aside id="queries-panel"'), html.indexOf('<dialog id="query-dialog"'));
  assert.match(panel, /id="queries-list"/);
  assert.doesNotMatch(panel, /id="query-form"/);
  assert.match(html, /<dialog id="query-dialog"[^>]*aria-labelledby="query-dialog-title"/);
  assert.match(html.slice(html.indexOf('<dialog id="query-dialog"')), /id="query-form"/);
});
