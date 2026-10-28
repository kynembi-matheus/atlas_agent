'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/app.js', 'utf8');

test('navigation identifies the active section and closes chat panels on other pages', () => {
  const nodes = new Map();
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {attributes: {}, hidden: false,
      setAttribute(key, value) { this.attributes[key] = value; },
      removeAttribute(key) { delete this.attributes[key]; }});
    return nodes.get(id);
  };
  const classes = new Set(['preview-open']);
  const context = vm.createContext({$, window: {location: {pathname: '/dashboards/example'}},
    document: {body: {classList: {toggle() {}, remove: key => classes.delete(key)}}}});
  vm.runInContext(source.slice(source.indexOf('function renderHistoryPage()'), source.indexOf('function navigatePage(')), context);
  context.renderHistoryPage();
  assert.equal($('open-dashboards').attributes['aria-current'], 'page');
  assert.equal($('dashboard-detail-page').hidden, false);
  assert.equal(classes.has('preview-open'), false);
  for (const path of ['/sessoes', '/historico', '/agendamentos']) {
    context.window.location.pathname = path;
    context.renderHistoryPage();
    const expected = path === '/agendamentos' ? 'open-schedules' : 'more-history';
    assert.equal($(expected).attributes['aria-current'], 'page');
    assert.equal($('open-dashboards').attributes['aria-current'], undefined);
    for (const [panel, toggle] of [['data-preview', 'toggle-preview'], ['queries-panel', 'toggle-queries']]) {
      assert.equal($(panel).hidden, true);
      assert.equal($(toggle).attributes['aria-expanded'], 'false');
    }
  }
  context.window.location.pathname = '/';
  context.renderHistoryPage();
  assert.equal($('chat-page').hidden, false);
  for (const id of ['open-schedules', 'more-history', 'open-dashboards']) assert.equal($(id).attributes['aria-current'], undefined);
});
