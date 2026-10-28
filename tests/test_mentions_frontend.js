'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness(handler) {
  const nodes = new Map(); const notices = [];
  class Node {
    constructor() { this.children = []; this.handlers = {}; this.attributes = {}; this.value = ''; this.maxLength = 16000; this.hidden = true; }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children = []; }
    setAttribute(key, value) { this.attributes[key] = value; }
    removeAttribute(key) { delete this.attributes[key]; }
    addEventListener(key, callback) { this.handlers[key] = callback; }
    focus() {}
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
    scrollIntoView() {}
    contains(target) { return this === target; }
  }
  const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const requests = [];
  const context = vm.createContext({$, URLSearchParams, databaseOptions: ['cora', 'synap'],
    el: (tag, cls, text) => { const node = new Node(); node.textContent = text; return node; },
    document: new Node(), notice: text => notices.push(text),
    api: async url => { requests.push(url); return {json: async () => handler(url)}; },
    tableReference: table => `Tabela PostgreSQL: database=${JSON.stringify(table.database)}, schema=${JSON.stringify(table.schema)}, tabela=${JSON.stringify(table.table)}.`,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/mentions.js'), 'utf8'), context);
  function type(value, caret = value.length) { $('prompt').value = value; $('prompt').setSelectionRange(caret, caret); return context.updateMentions(); }
  function key(key, extra = {}) { const event = {key, preventDefault() { this.prevented = true; }, ...extra}; $('prompt').handlers.keydown(event); return event; }
  return {$, context, requests, type, key, notices};
}
const skills = [{name: 'Relatórios em PDF', document_path: 'pdf_report/SKILL.md', description: 'Relatório'},
  {name: 'Análise comparativa', document_path: 'skills/comparative-analysis/SKILL.md', description: 'Comparar'}];

test('? filters favorites and selection supplies the saved ID without executing SQL', async () => {
  const favorite = {id: '12345678-abcd-4321-abcd-123456789012', name: 'Crédito mensal', database: 'cora', description: 'Indicadores'};
  const h = harness(() => ({queries: [favorite]}));
  const text = 'Compare ?credito por mês';
  await h.type(text, text.indexOf(' por'));
  assert.equal(h.$('mention-status').textContent, 'Queries favoritas');
  assert.equal(h.$('mention-options').children.length, 1);
  h.key('Enter');
  assert.match(h.$('prompt').value, /^Compare \?Crédito mensal/);
  assert.ok(h.$('prompt').value.endsWith(' por mês'));
  const expanded = h.context.expandChatMentions(h.$('prompt').value);
  assert.match(expanded, /run_favorite_query/);
  assert.ok(expanded.includes(favorite.id));
  assert.match(expanded, /ainda não foi executada/);
  assert.deepEqual(h.requests, ['/api/queries']);
  assert.equal(h.context.expandChatMentions('Sem favorita.'), 'Sem favorita.');
});

test('? empty list, error retry, Escape and stale response follow the menu behavior', async () => {
  let fail = true;
  const h = harness(() => { if (fail) throw new Error('Offline'); return {queries: []}; });
  await h.type('?'); assert.match(h.$('mention-status').textContent, /Offline/);
  fail = false; await h.type('?'); assert.equal(h.$('mention-status').textContent, 'Nenhum resultado.');
  h.key('Escape'); assert.equal(h.$('mention-menu').hidden, true);
  let resolve;
  const stale = harness(() => new Promise(done => { resolve = done; }));
  const pending = stale.type('?'); await Promise.resolve();
  await stale.type('Pergunta normal'); resolve({queries: []}); await pending;
  assert.equal(stale.$('mention-menu').hidden, true);
});

test('/ filters without accents and selection preserves text around the cursor', async () => {
  const h = harness(() => ({skills}));
  const text = 'Preciso /relatorio com gráficos';
  await h.type(text, text.indexOf(' com'));
  assert.equal(h.$('mention-options').children.length, 1);
  assert.equal(h.key('Enter').prevented, true);
  assert.match(h.$('prompt').value, /^Preciso \/Relatórios em PDF/);
  assert.match(h.context.expandChatMentions(h.$('prompt').value), /pdf_report\/SKILL.md/);
  assert.ok(h.$('prompt').value.endsWith(' com gráficos'));
  assert.equal(h.$('mention-menu').hidden, true);
  assert.equal(h.context.expandChatMentions('Apaguei a seleção.'), 'Apaguei a seleção.');
});

test('@ offers permitted databases then explicit public table references', async () => {
  const h = harness(url => url.includes('/databases') ? {databases: ['cora', 'private']} : {tables: [{schema: 'public', table: 'vendas'}]});
  await h.type('Compare @');
  assert.equal(h.$('mention-options').children.length, 1);
  h.key('Enter');
  // Wait for asynchronous table discovery from database selection.
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.$('prompt').value, 'Compare @cora.');
  h.key('Enter');
  assert.equal(h.$('prompt').value, 'Compare @cora.public.vendas ');
  assert.match(h.context.expandChatMentions(h.$('prompt').value), /^Compare Tabela PostgreSQL: database="cora", schema="public", tabela="vendas"/);
  assert.equal(h.requests.some(url => url.includes('preview')), false);
  assert.match(h.requests[1], /database=cora&schema=public/);
});

test('keyboard selection wraps; Escape closes; modified Enter remains available to the composer', async () => {
  const h = harness(() => ({skills}));
  await h.type('/');
  h.key('ArrowUp');
  assert.equal(h.$('prompt').attributes['aria-activedescendant'], 'mention-1');
  assert.equal(h.key('Enter', {ctrlKey: true}).prevented, undefined);
  h.key('Enter');
  assert.match(h.$('prompt').value, /Análise comparativa/);
  await h.type('/'); h.key('Escape');
  assert.equal(h.$('mention-menu').hidden, true);
  assert.equal(h.$('prompt').attributes['aria-activedescendant'], undefined);
});

test('stale results cannot reopen dismissed menus or replace a newer search', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  const pending = h.type('/');
  await Promise.resolve();
  await h.type('Pergunta comum');
  resolve({skills}); await pending;
  assert.equal(h.$('mention-menu').hidden, true);
});

test('empty matches, failed requests, and length limits preserve the prompt', async () => {
  let fail = true;
  const h = harness(() => { if (fail) throw new Error('Offline'); return {skills}; });
  await h.type('/');
  assert.match(h.$('mention-status').textContent, /Offline/);
  fail = false; await h.type('/inexistente');
  assert.equal(h.$('mention-status').textContent, 'Nenhum resultado.');
  await h.type('/'); h.$('prompt').maxLength = 3; h.key('Enter');
  assert.equal(h.$('prompt').value, '/'); assert.equal(h.notices.length, 1);
});

test('email addresses, URLs and selections do not open the picker', async () => {
  const h = harness(() => { throw new Error('Unexpected request'); });
  for (const text of ['email@empresa.com', 'https://site.com/path', 'total / 2']) {
    await h.type(text); assert.equal(h.$('mention-menu').hidden, true);
  }
  assert.equal(h.requests.length, 0);
});

test('moving the cursor or selecting text cannot insert a stale suggestion', async () => {
  const h = harness(() => ({skills}));
  await h.type('Pergunta /');
  h.$('prompt').setSelectionRange(0, 4);
  h.key('Enter');
  assert.equal(h.$('prompt').value, 'Pergunta /');
  assert.equal(h.$('mention-menu').hidden, true);
});

test('typing while loading shares the request and displays the latest filter', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  const first = h.type('/');
  await Promise.resolve();
  const second = h.type('/analise');
  await Promise.resolve();
  assert.equal(h.requests.length, 1);
  resolve({skills}); await Promise.all([first, second]);
  assert.equal(h.$('mention-options').children.length, 1);
  assert.equal(h.$('mention-options').children[0].children[0].textContent, 'Análise comparativa');
});
