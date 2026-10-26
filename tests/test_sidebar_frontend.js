'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../frontend/sidebar.js'), 'utf8');
function harness(initial = null, unavailable = false) {
  const attributes = new Map(), rootAttributes = new Map(), stored = new Map();
  if (initial !== null) stored.set('scd-sidebar-collapsed', initial);
  const button = {setAttribute: (key, value) => attributes.set(key, value), addEventListener(event, fn) { this[event] = fn; }};
  const window = {addEventListener(event, fn) { this[event] = fn; }};
  vm.runInNewContext(source, {window, document: {getElementById: () => button,
    documentElement: {setAttribute: (key, value) => rootAttributes.set(key, value), getAttribute: key => rootAttributes.get(key)}},
    localStorage: {getItem(key) { if (unavailable) throw new Error('blocked'); return stored.get(key); },
      setItem(key, value) { if (unavailable) throw new Error('blocked'); stored.set(key, value); }}});
  return {button, attributes, rootAttributes, stored, window};
}
test('sidebar restores collapsed preference and toggles accessibly in both directions', () => {
  const h = harness('true');
  assert.equal(h.attributes.get('aria-expanded'), 'false');
  assert.equal(h.button.title, 'Expandir sidebar');
  h.button.click();
  assert.equal(h.rootAttributes.get('data-sidebar-collapsed'), 'false');
  assert.equal(h.attributes.get('aria-expanded'), 'true');
  assert.equal(h.stored.get('scd-sidebar-collapsed'), 'false');
  h.button.click();
  assert.equal(h.attributes.get('aria-label'), 'Expandir sidebar');
  assert.equal(h.stored.get('scd-sidebar-collapsed'), 'true');
});
test('sidebar works with blocked storage and follows changes from another tab', () => {
  const h = harness(null, true);
  h.button.click();
  assert.equal(h.attributes.get('aria-expanded'), 'false');
  h.window.storage({key: 'scd-sidebar-collapsed', newValue: 'false'});
  assert.equal(h.attributes.get('aria-expanded'), 'true');
});
