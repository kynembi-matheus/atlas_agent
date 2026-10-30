'use strict';
(() => {
  const button = document.getElementById('toggle-sidebar');
  const root = document.documentElement;
  const key = 'scd-sidebar-collapsed';
  function apply(collapsed) {
    root.setAttribute('data-sidebar-collapsed', String(collapsed));
    button.setAttribute('aria-expanded', String(!collapsed));
    const label = collapsed ? 'Expandir sidebar' : 'Minimizar sidebar';
    button.setAttribute('aria-label', label); button.title = label;
  }
  let initial = true;
  try { initial = localStorage.getItem(key) !== 'false'; } catch (_) { /* Preferência vale nesta página. */ }
  apply(initial);
  button.addEventListener('click', () => {
    const collapsed = root.getAttribute('data-sidebar-collapsed') !== 'true';
    apply(collapsed);
    try { localStorage.setItem(key, String(collapsed)); } catch (_) { /* Preferência vale nesta página. */ }
  });
  window.addEventListener('storage', event => { if (event.key === key) apply(event.newValue === 'true'); });
})();
