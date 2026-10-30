'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/app.js', 'utf8');

for (const [checked, disabled, expected, dashboard] of [[false, false, false, false], [true, false, true, false], [true, true, false, true], [true, false, true, true]]) {
  test(`preferences submitted: web=${checked}, disabled=${disabled}, dashboard=${dashboard}`, async () => {
    const nodes = new Map();
    const $ = id => {
      if (!nodes.has(id)) nodes.set(id, {value: '', handlers: {}, addEventListener(name, fn) { this.handlers[name] = fn; }});
      return nodes.get(id);
    };
    $('prompt').value = 'Pesquise as fontes'; $('prompt').maxLength = 16000;
    Object.assign($('web-search-enabled'), {disabled, getAttribute: () => String(checked)});
    $('output-dashboard').checked = dashboard;
    const requests = [];
    const context = vm.createContext({$, state: {files: [], conversationId: null}, notice() {},
      renderAttachments() {}, selectRun() {}, api: async (_, options) => {
        requests.push(JSON.parse(options.body)); return {json: async () => ({id: 'run'})};
      }});
    vm.runInContext(source.slice(source.indexOf("$('prompt-form').addEventListener('submit'"),
      source.indexOf("$('prompt').addEventListener('keydown'")), context);
    await $('prompt-form').handlers.submit({preventDefault() {}});
    assert.equal(requests.length, 1);
    assert.equal(requests[0].web_search_enabled, expected);
    assert.equal(requests[0].output_format, dashboard ? 'sites' : 'auto');
  });
}

test('web control is a toggle button at the bottom of the composer and starts off', () => {
  const html = fs.readFileSync('frontend/index.html', 'utf8');
  const form = html.slice(html.indexOf('<form id="prompt-form"'), html.indexOf('</form>', html.indexOf('<form id="prompt-form"')));
  assert.ok(form.indexOf('id="web-search-enabled"') > form.indexOf('id="send"'));
  assert.match(form, /<button id="web-search-enabled"[^>]+type="button"[^>]+aria-pressed="false"/);
  assert.doesNotMatch(form, /type="checkbox"/);
  assert.match(form, /href="\/static\/vendor\/lucide\/sprite.svg\?v=0.468.0#icon-globe"/);
  assert.match(form, /<fieldset class="output-options">/);
  assert.match(form, /id="output-normal"[^>]+checked/);
  assert.match(form, />Normal</);
});

test('global disable clears the selected web option', async () => {
  const toggle = {pressed: 'true', setAttribute(_, value) { this.pressed = value; }};
  const context = vm.createContext({$: id => id === 'web-search-enabled' ? toggle : {},
    api: async () => ({json: async () => ({internet_enabled: false, llm_configured: true})}), notice() {}});
  vm.runInContext(source.slice(source.indexOf('async function refreshStatus'), source.indexOf('async function refreshHistory')), context);
  await context.refreshStatus();
  assert.equal(toggle.disabled, true);
  assert.equal(toggle.pressed, 'false');
});

test('web button toggles on and off, and stays off when disabled', () => {
  const button = {pressed: 'false', disabled: false,
    getAttribute() { return this.pressed; }, setAttribute(_, value) { this.pressed = value; },
    addEventListener(_, handler) { this.click = () => handler({currentTarget: this}); }};
  const context = vm.createContext({$: () => button});
  vm.runInContext(source.slice(source.indexOf("$('web-search-enabled').addEventListener('click'"),
    source.indexOf("$('prompt-form').addEventListener('submit'")), context);
  button.click(); assert.equal(button.pressed, 'true');
  button.click(); assert.equal(button.pressed, 'false');
  button.disabled = true; button.click(); assert.equal(button.pressed, 'false');
});
