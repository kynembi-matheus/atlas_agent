'use strict';
// Applied before CSS to avoid flashing the light theme on reload.
(() => {
  let theme = 'light';
  try { if (localStorage.getItem('scd-theme') === 'dark') theme = 'dark'; }
  catch (_) { /* Theme remains usable when browser storage is blocked. */ }
  document.documentElement.dataset.theme = theme;
})();
