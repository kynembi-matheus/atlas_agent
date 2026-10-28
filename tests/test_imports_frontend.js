'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Node {
  constructor() { this.children = []; this.handlers = {}; this.attributes = {}; this.hidden = true; this.value = ''; this.classList = {toggle() {}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
const dataset = {dataset_id: 'temporary-id', row_count: 1, columns: ['Nome'], preview: [{Nome: '<script>literal</script>'}],
  source: {filename: 'dados.xlsx', sheet: 'Carteira', format: 'xlsx', inferred_types: {Nome: 'string'}, extraction_warnings: []}};
function harness(api) {
  const nodes = new Map(), windowEvents = {}, notices = [];
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const state = {files: [], uploading: false, run: null};
  const context = vm.createContext({appUrl: path => path, appPath: () => context.window.location.pathname, $, state, api, notice: text => notices.push(text), renderAttachments() {},
    el: (tag, cls, text) => { const node = new Node(); node.tag = tag; node.textContent = text; return node; },
    FormData: class {append(_, file) { this.file = file; }}, document: {body: new Node()},
    window: {addEventListener: (name, fn) => { windowEvents[name] = fn; }}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/chat-drag.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/imports.js'), 'utf8'), context);
  return {$, context, state, notices, windowEvents};
}

test('temporary importer shows inferred types and adds data to the chat without sending it', async () => {
  const {$, state} = harness(async () => ({json: async () => ({datasets: [dataset]})}));
  const input = {files: [{name: 'dados.xlsx'}], value: 'file'};
  await $('temporary-files').handlers.change({target: input});
  assert.equal(state.files.length, 1);
  assert.equal(state.files[0].id, dataset.dataset_id);
  assert.match(state.files[0].filename, /temporário/);
  const card = $('import-results').children[0];
  assert.equal(card.children[2].children[0].textContent, 'Nome: Texto');
  assert.match($('import-status').textContent, /Confira a amostra/);
  assert.equal(input.value, '');
  assert.equal(state.uploading, false);
});

test('valid imports survive another file failure and controls are locked during inference', async () => {
  const pending = [];
  const {$, state} = harness(async (_, options) => {
    if (options.body.file.name === 'bad.csv') throw new Error('Inválido');
    return await new Promise(resolve => pending.push(resolve));
  });
  const promise = $('temporary-files').handlers.change({target: {files: [{name: 'good.csv'}, {name: 'bad.csv'}]}});
  assert.equal(state.uploading, true);
  assert.equal($('new-run').disabled, true);
  assert.equal($('send').disabled, true);
  pending[0]({json: async () => ({datasets: [dataset]})});
  await promise;
  assert.equal(state.files.length, 1);
  assert.match($('import-status').textContent, /bad.csv: Inválido/);
  assert.equal($('new-run').disabled, false);
});

test('opening importer closes the other panels and Escape restores focus', () => {
  const {$, context} = harness();
  context.setImportsOpen(true);
  assert.equal($('imports-panel').hidden, false);
  assert.equal($('data-preview').hidden, true);
  assert.equal($('skills-panel').hidden, true);
  $('imports-panel').handlers.keydown({key: 'Escape'});
  assert.equal($('imports-panel').hidden, true);
  assert.equal($('toggle-imports').focused, true);
});

test('session initialization is shared, uses a scoped header and replaces the previous session on reload', async () => {
  const calls = [], values = new Map([['scd-import-session', 'previous-session']]);
  const state = {sessionId: null, sessionPromise: null};
  const context = vm.createContext({appUrl: path => path, appPath: () => context.window.location.pathname, state, Headers,
    sessionStorage: {getItem: key => values.get(key), setItem: (key, value) => values.set(key, value)},
    fetch: async (url, options) => {
      calls.push({url, options});
      return {ok: true, json: async () => ({session_id: 'new-session'})};
    }});
  const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf('async function api('), source.indexOf('function el(')), context);
  await Promise.all([context.api('/api/skills'), context.api('/api/runs')]);
  assert.equal(calls.filter(call => call.url === '/api/import-sessions').length, 1);
  assert.equal(calls[0].options.headers.get('X-Data-Session'), 'previous-session');
  assert.equal(calls[1].options.headers.get('X-Data-Session'), 'new-session');
  assert.equal(calls[2].options.headers.get('X-Data-Session'), 'new-session');
  assert.equal(values.get('scd-import-session'), 'new-session');
});

test('New conversation replaces the session before resetting the chat', async () => {
  const nodes = new Map(), order = [];
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const context = vm.createContext({appUrl: path => path, appPath: () => context.window.location.pathname, $, state: {uploading: false, files: [dataset]},
    ensureDataSession: async () => order.push('ensure'), rotateDataSession: async () => order.push('rotate'),
    stopPolling: () => order.push('stop'), renderAttachments() {}, notice() {}, refreshHistory() {}, navigatePage() {}});
  const source = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf("$('new-run').addEventListener"), source.indexOf("$('more-history').addEventListener")), context);
  await $('new-run').handlers.click();
  assert.deepEqual(order, ['ensure', 'rotate', 'stop']);
  assert.equal($('import-results').children.length, 0);
});

test('Import button is directly next to Choose data inside the chat container', () => {
  const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
  const toolbar = html.slice(html.indexOf('<nav class="workspace-choices"'), html.indexOf('</nav>', html.indexOf('<nav class="workspace-choices"')));
  assert.match(toolbar, /id="toggle-preview"[\s\S]*id="toggle-imports"[\s\S]*id="toggle-skills"/);
});

test('temporary files above 500 MB are rejected before uploading', async () => {
  let calls = 0;
  const {$, state} = harness(async () => { calls++; });
  await $('temporary-files').handlers.change({target: {files: [{name: 'grande.csv', size: 500 * 1024 * 1024 + 1}]}});
  assert.equal(calls, 0);
  assert.equal(state.files.length, 0);
  assert.match($('import-status').textContent, /500 MB por arquivo/);
});

test('Import panel lists session data while new uploads open in a separate popup', async () => {
  const {$, context} = harness(async () => ({json: async () => ({datasets: [dataset]})}));
  context.setImportsOpen(true);
  assert.notEqual($('import-dialog').open, true);
  $('new-import').handlers.click();
  assert.equal($('import-dialog').open, true);
  assert.equal($('temporary-files').focused, true);
  await $('temporary-files').handlers.change({target: {files: [{name: 'dados.xlsx'}]}});
  assert.equal($('import-dialog').open, false);
  assert.equal($('imports-panel').hidden, false);
  assert.equal($('import-results').children.length, 1);
  assert.match($('import-summary').textContent, /^1 dataset/);
  context.setImportsOpen(false); context.setImportsOpen(true);
  assert.equal($('import-results').children.length, 1);
  $('new-import').handlers.click(); $('cancel-import').handlers.click();
  assert.equal($('import-dialog').open, false);
  assert.equal($('import-results').children.length, 1);
});

test('partial failure remains visible in the popup and preserves previous session imports', async () => {
  const {$, context} = harness(async (_, options) => {
    if (options.body.file.name === 'bad.csv') throw new Error('Inválido');
    return {json: async () => ({datasets: [dataset]})};
  });
  context.showImportedDataset({...dataset, dataset_id: 'previous'});
  $('new-import').handlers.click();
  await $('temporary-files').handlers.change({target: {files: [{name: 'good.csv'}, {name: 'bad.csv'}]}});
  assert.equal($('import-dialog').open, true);
  assert.match($('import-status').textContent, /bad.csv: Inválido/);
  assert.equal($('import-results').children.length, 2);
  assert.match($('import-summary').textContent, /^2 dataset/);
  assert.equal($('cancel-import').disabled, false);
});

test('upload locks the popup until completion and Escape does not dismiss progress', async () => {
  let resolve;
  const {$} = harness(() => new Promise(done => { resolve = done; }));
  $('new-import').handlers.click();
  const pending = $('temporary-files').handlers.change({target: {files: [{name: 'dados.xlsx'}]}});
  let prevented = false;
  $('import-dialog').handlers.cancel({preventDefault() { prevented = true; }});
  $('close-import-dialog').handlers.click();
  assert.equal(prevented, true);
  assert.equal($('import-dialog').open, true);
  assert.equal($('new-import').disabled, true);
  resolve({json: async () => ({datasets: [dataset]})}); await pending;
  assert.equal($('new-import').disabled, false);
  assert.equal($('import-dialog').open, false);
});

test('file picker and progress are inside a labelled popup, separate from session data', () => {
  const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
  const panel = html.slice(html.indexOf('<aside id="imports-panel"'), html.indexOf('<aside id="skills-panel"'));
  assert.match(panel, /id="import-results"/);
  assert.match(panel, /id="new-import"/);
  assert.doesNotMatch(panel, /id="temporary-files"/);
  const dialog = html.slice(html.indexOf('<dialog id="import-dialog"'));
  assert.match(dialog, /aria-labelledby="import-dialog-title"/);
  assert.match(dialog, /id="temporary-files"/);
  assert.match(dialog, /id="import-status"/);
});
