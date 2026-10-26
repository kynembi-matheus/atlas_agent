'use strict';
// Código fixo da aplicação; o agente fornece apenas dados e widgets declarativos.
const filterForm = document.querySelector?.('[data-dashboard-filters]');
if (filterForm) {
  const sendFilters = clear => {
    const filters = {};
    filterForm.querySelectorAll('[data-dashboard-filter]').forEach(control => {
      if (!clear && control.value) filters[control.dataset.dashboardFilter] = control.value;
    });
    window.parent.postMessage({type: 'dashboard-filters', filters}, '*');
  };
  filterForm.addEventListener('submit', event => { event.preventDefault(); sendFilters(false); });
  filterForm.addEventListener('reset', () => sendFilters(true));
  filterForm.querySelectorAll('select').forEach(control => {
    control.addEventListener('change', () => sendFilters(false));
  });
}
document.querySelectorAll('.widget-table').forEach(section => {
  const table = section.querySelector('table');
  if (!table) return;
  const body = table.querySelector('tbody');
  const original = [...body.rows];
  const search = section.querySelector('[data-table-search]');
  const previous = section.querySelector('[data-prev]');
  const next = section.querySelector('[data-next]');
  const status = section.querySelector('[data-page-status]');
  let page = 0, sortColumn = null, direction = 1;
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  const numeric = value => value.trim() !== '' && Number.isFinite(Number(value));
  function render() {
    const query = normalize(search.value.trim());
    const rows = original.filter(row => normalize(row.textContent).includes(query));
    if (sortColumn !== null) rows.sort((left, right) => {
      const a = left.cells[sortColumn].dataset.value;
      const b = right.cells[sortColumn].dataset.value;
      return direction * (numeric(a) && numeric(b) ? Number(a) - Number(b) : a.localeCompare(b, 'pt-BR', {numeric: true}));
    });
    const pages = Math.max(1, Math.ceil(rows.length / 10));
    page = Math.min(page, pages - 1);
    original.forEach(row => { row.hidden = true; });
    rows.forEach((row, index) => { row.hidden = index < page * 10 || index >= (page + 1) * 10; body.append(row); });
    status.textContent = `${rows.length} resultados · ${page + 1}/${pages}`;
    previous.disabled = page === 0; next.disabled = page === pages - 1;
  }
  section.querySelectorAll('[data-sort]').forEach(button => {
    button.addEventListener('click', () => {
      const column = Number(button.dataset.sort);
      direction = sortColumn === column ? -direction : 1; sortColumn = column; page = 0;
      section.querySelectorAll('th').forEach(header => header.setAttribute('aria-sort', 'none'));
      button.closest('th').setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');
      render();
    });
  });
  search.addEventListener('input', () => { page = 0; render(); });
  previous.addEventListener('click', () => { if (page > 0) { page--; render(); } });
  next.addEventListener('click', () => { page++; render(); });
  render();
});
