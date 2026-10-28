'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('prefix is applied to application URLs and stripped for navigation', () => {
  const source = fs.readFileSync('frontend/app.js', 'utf8');
  const helpers = source.slice(source.indexOf('const appRoot'), source.indexOf('const state'));
  const context = vm.createContext({document: {querySelector: () => ({content: '/atlas'})},
    window: {location: {pathname: '/atlas/dashboards'}}});
  vm.runInContext(helpers, context);
  assert.equal(context.appUrl('/api/status'), '/atlas/api/status');
  assert.equal(context.appPath(), '/dashboards');
  context.window.location.pathname = '/atlas/';
  assert.equal(context.appPath(), '/');
});
