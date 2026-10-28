'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/app.js', 'utf8');

function setup({disabled = false, menuOpen = false} = {}) {
  let handler, submitted = 0;
  const prompt = {value: 'AntesDepois', selectionStart: 5, selectionEnd: 5, maxLength: 16000, events: [],
    addEventListener(_, fn) { handler = fn; },
    setRangeText(text, start, end) { this.value = this.value.slice(0, start) + text + this.value.slice(end); this.selectionStart = this.selectionEnd = start + text.length; },
    dispatchEvent(event) { this.events.push(event.type); }};
  const nodes = {prompt, send: {disabled},
    'mention-menu': {hidden: !menuOpen}, 'prompt-form': {requestSubmit() { submitted++; }}};
  const context = vm.createContext({$: id => nodes[id], Event});
  vm.runInContext(source.slice(source.indexOf("$('prompt').addEventListener('keydown'"),
    source.indexOf("$('cancel-run').addEventListener('click'")), context);
  return {prompt, get submitted() { return submitted; }, key(options = {}) {
    const event = {key: 'Enter', preventDefault() { this.prevented = true; }, ...options};
    handler(event); return event;
  }};
}

test('Enter sends and prevents a newline', () => {
  const app = setup(); assert.equal(app.key().prevented, true); assert.equal(app.submitted, 1);
});
test('Alt+Enter explicitly inserts a newline at the caret without submitting', () => {
  const app = setup(); assert.equal(app.key({altKey: true}).prevented, true); assert.equal(app.submitted, 0);
  assert.equal(app.prompt.value, 'Antes\nDepois');
  assert.equal(app.prompt.selectionStart, 6);
  assert.deepEqual(app.prompt.events, ['input']);
});

test('Alt+Enter replaces selected text and respects maxlength', () => {
  const app = setup({menuOpen: true});
  app.prompt.selectionEnd = 11; app.key({altKey: true});
  assert.equal(app.prompt.value, 'Antes\n'); assert.equal(app.submitted, 0);
  app.prompt.maxLength = app.prompt.value.length; app.key({altKey: true});
  assert.equal(app.prompt.value, 'Antes\n');
});
test('composition and mention selection cannot submit a message', () => {
  const app = setup(); app.key({isComposing: true}); assert.equal(app.submitted, 0);
  const menu = setup({menuOpen: true}); assert.equal(menu.key().prevented, undefined); assert.equal(menu.submitted, 0);
});
test('disabled send and handled events cannot submit', () => {
  const app = setup({disabled: true}); assert.equal(app.key().prevented, true); assert.equal(app.submitted, 0);
  const handled = setup(); handled.key({defaultPrevented: true}); assert.equal(handled.submitted, 0);
});

test('account switch creates a fresh import session without deleting another account session', async () => {
  const requests = [], state = {sessionId: null};
  const context = vm.createContext({state, Headers, sessionStorage: {getItem: () => 'old-user-session', setItem() {}},
    fetch: async (_, options) => {
      requests.push(options);
      return requests.length === 1 ? {ok: false, status: 410} : {ok: true, json: async () => ({session_id: 'new-user-session'})};
    }});
  vm.runInContext(source.slice(source.indexOf('async function rotateDataSession'), source.indexOf('function el(')), context);
  await context.rotateDataSession();
  assert.equal(state.sessionId, 'new-user-session');
  assert.equal(requests[0].headers.get('X-Data-Session'), 'old-user-session');
  assert.equal(requests[1].headers, undefined);
});
