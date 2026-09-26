// Reports: time spent and planned in any range of dates, per day, per folder and per task.

import { api } from '../api.js';
import { kpiHTML } from '../components/kpi.js';
import { bindPaneTabs, paneTabsHTML } from '../components/panes.js';
import { openTaskDrawer } from '../components/taskDrawer.js';
import { timeBarsHTML } from '../components/timeBars.js';
import { folderName, store } from '../store.js';
import {
  STATUS_LABEL, addDays, dateISO, esc, fmtDay, fmtMinutes, icons, parseDay, setPageTitle,
  showError, startOfWeek, toast, todayISO,
} from '../util.js';

const PRESETS = [
  ['today', 'Today', (t) => [t, t]],
  ['this-week', 'This week', (t) => [startOfWeek(t), addDays(startOfWeek(t), 6)]],
  ['last-week', 'Last week', (t) => [addDays(startOfWeek(t), -7), addDays(startOfWeek(t), -1)]],
  ['last-30', 'Last 30 days', (t) => [addDays(t, -29), t]],
  ['this-month', 'This month', (t) => [new Date(t.getFullYear(), t.getMonth(), 1), new Date(t.getFullYear(), t.getMonth() + 1, 0)]],
  ['last-month', 'Last month', (t) => [new Date(t.getFullYear(), t.getMonth() - 1, 1), new Date(t.getFullYear(), t.getMonth(), 0)]],
  ['this-year', 'This year', (t) => [new Date(t.getFullYear(), 0, 1), new Date(t.getFullYear(), 11, 31)]],
];
const MAX_DAY_COLUMNS = 62; // past two months, the chart shows weeks
const MAX_AXIS_LABELS = 8;
const TICK_STEPS = [15, 30, 60, 120, 180, 240, 360, 480, 720, 1200, 1440, 2400, 3600, 6000];

// The chosen range and project survive leaving the page and coming back.
// project: '' for every folder, 'inbox', or a folder id.
const state = { preset: 'this-week', from: null, to: null, project: '' };

function projectFilter() {
  if (state.project === 'inbox') return { inbox: true };
  return state.project ? { folder_id: state.project } : {};
}

function applyPreset() {
  const preset = PRESETS.find(([key]) => key === state.preset);
  if (!preset) return;
  const [from, to] = preset[2](parseDay(todayISO()));
  state.from = dateISO(from);
  state.to = dateISO(to);
}

// --- Chart: time spent per day (or week), one series ---------------------------------

function columns(days) {
  if (days.length <= MAX_DAY_COLUMNS) {
    return {
      unit: 'day',
      items: days.map((d) => ({
        start: d.day,
        label: fmtDay(d.day, { weekday: 'short', day: 'numeric' }),
        name: fmtDay(d.day, { weekday: 'long', day: 'numeric', month: 'long' }),
        tracked: d.tracked_minutes,
        planned: d.planned_minutes,
      })),
    };
  }
  const weeks = new Map();
  for (const d of days) {
    const start = dateISO(startOfWeek(parseDay(d.day)));
    const week = weeks.get(start) ?? { start, tracked: 0, planned: 0 };
    week.tracked += d.tracked_minutes;
    week.planned += d.planned_minutes;
    weeks.set(start, week);
  }
  return {
    unit: 'week',
    items: [...weeks.values()].map((w) => ({
      ...w,
      label: fmtDay(w.start, { day: 'numeric', month: 'short' }),
      name: `Week of ${fmtDay(w.start, { day: 'numeric', month: 'long' })}`,
    })),
  };
}

/** A clean top value and gridlines for a scale that must reach `max` minutes. */
function scale(max) {
  const step = TICK_STEPS.find((s) => max / s <= 4) ?? Math.ceil(max / 240) * 60;
  const top = Math.max(step, Math.ceil(max / step) * step);
  const ticks = [];
  for (let v = 0; v <= top; v += step) ticks.push(v);
  return { top, ticks };
}

function chartHTML({ unit, items }) {
  const max = Math.max(...items.map((i) => i.tracked));
  if (!max) return '<p class="empty">No time spent in this range.</p>';
  const { top, ticks } = scale(max);
  const every = Math.ceil(items.length / MAX_AXIS_LABELS);
  const height = (m) => (m ? `max(2px, ${(m / top) * 100}%)` : '0');
  return `
    <div class="bar-chart" role="group" aria-label="${esc(`Time spent per ${unit}`)}">
      <div class="bc-plot">
        ${ticks.map((v) => `<div class="bc-gridline" style="bottom:${(v / top) * 100}%"><span class="bc-tick">${fmtMinutes(v)}</span></div>`).join('')}
        <div class="bc-columns">${items
          .map(
            (i) => `<div class="bc-col" tabindex="0" data-tip-value="${fmtMinutes(i.tracked)} spent" data-tip-label="${esc(i.name)}"
              aria-label="${esc(`${i.name}: ${fmtMinutes(i.tracked)} spent`)}"><span class="bc-bar" style="height:${height(i.tracked)}"></span></div>`,
          )
          .join('')}</div>
      </div>
      <div class="bc-axis" aria-hidden="true">${items
        .map((i, n) => `<span>${n % every === 0 ? esc(i.label) : ''}</span>`)
        .join('')}</div>
    </div>
    <details class="chart-table">
      <summary>Show as table</summary>
      <table class="report-table">
        <thead><tr><th>${unit === 'day' ? 'Day' : 'Week'}</th><th class="num">Spent</th><th class="num">Planned</th></tr></thead>
        <tbody>${items
          .map((i) => `<tr><td>${esc(i.name)}</td><td class="num">${fmtMinutes(i.tracked)}</td><td class="num">${fmtMinutes(i.planned)}</td></tr>`)
          .join('')}</tbody>
      </table>
    </details>`;
}

// --- Tables & page -------------------------------------------------------------------

function tasksHTML(rows) {
  if (!rows.length) return '<p class="empty">No time on tasks or appointments in this range.</p>';
  return `<table class="report-table">
    <thead><tr>
      <th>Task</th><th class="hide-sm">Folder</th><th class="hide-sm">Status</th>
      <th class="num">Spent</th><th class="num">Planned</th>
    </tr></thead>
    <tbody>${rows
      .map(
        (r) => `<tr${r.task_id ? ` class="is-link" data-task-id="${r.task_id}" tabindex="0"` : ''}>
          <td><span class="rt-name"><i class="dot" style="--c:${r.color}"></i>${esc(r.title)}</span></td>
          <td class="hide-sm">${esc(folderName(r.folder_id))}</td>
          <td class="hide-sm">${r.status ? STATUS_LABEL[r.status] : '<span class="muted">Appointment</span>'}</td>
          <td class="num">${fmtMinutes(r.tracked_minutes)}</td>
          <td class="num muted">${fmtMinutes(r.planned_minutes)}</td>
        </tr>`,
      )
      .join('')}</tbody>
  </table>`;
}

function reportHTML(report) {
  const chart = report.days.length > 1 ? columns(report.days) : null;
  const perDay = Math.round(report.tracked_minutes / report.days.length);
  const byFolder = !state.project; // one project: its folder bar would only repeat the totals
  return `
    <div class="pane report-summary" data-pane="summary">
      <div class="kpi-row">
        ${kpiHTML('Time spent', fmtMinutes(report.tracked_minutes))}
        ${kpiHTML('Planned', fmtMinutes(report.planned_minutes))}
        ${kpiHTML('Tasks completed', String(report.completed_tasks))}
        ${chart ? kpiHTML('Spent per day, on average', fmtMinutes(perDay)) : ''}
      </div>
      ${
        chart
          ? `<section class="card">
              <header class="card-header"><h2>Time spent per ${chart.unit}</h2></header>
              ${chartHTML(chart)}
            </section>`
          : ''
      }
      ${
        byFolder
          ? `<section class="card">
              <header class="card-header"><h2>By folder</h2></header>
              ${timeBarsHTML(report.folders, 'No time in this range.')}
            </section>`
          : ''
      }
    </div>
    <section class="card slot pane report-tasks" data-pane="tasks">
      <header class="card-header"><h2>By task</h2><span class="count">${report.tasks.length}</span></header>
      <div class="slot-body">${tasksHTML(report.tasks)}</div>
    </section>`;
}

export async function mount(root) {
  setPageTitle('Reports');
  if (state.preset !== 'custom' || !state.from) applyPreset();
  root.innerHTML = `
    <form class="range-bar" aria-label="Report filters">
      <select name="preset" aria-label="Range">
        ${PRESETS.map(([key, label]) => `<option value="${key}">${label}</option>`).join('')}
        <option value="custom">Custom range</option>
      </select>
      <input type="date" name="from" aria-label="From" required>
      <span class="muted" aria-hidden="true">–</span>
      <input type="date" name="to" aria-label="To" required>
      <select name="project" aria-label="Project"></select>
      <span class="spacer"></span>
      <a class="btn" data-export download aria-label="Export to Excel"
        title="Download this report, with every calendar block, as an Excel file">
        ${icons.download}<span class="btn-label">Export to Excel</span></a>
    </form>
    ${paneTabsHTML([['summary', 'Summary'], ['tasks', 'By task']])}
    <div class="report panes" data-report></div>`;

  const form = root.querySelector('.range-bar');
  const content = root.querySelector('[data-report]');
  const exportLink = form.querySelector('[data-export]');
  const tabs = bindPaneTabs(root, 'reports');
  let loading = 0;

  // Folders can be added, renamed or deleted elsewhere: rebuild the list on every load.
  const fillProjects = () => {
    const options = [['', 'All projects'], ['inbox', 'Inbox'], ...store.folders.map((f) => [String(f.id), f.name])];
    if (!options.some(([value]) => value === state.project)) state.project = '';
    form.elements.project.innerHTML = options
      .map(([value, label]) => `<option value="${value}">${esc(label)}</option>`)
      .join('');
    form.elements.project.value = state.project;
  };

  const syncForm = () => {
    form.classList.toggle('is-custom', state.preset === 'custom'); // phones show the dates only then
    form.elements.preset.value = state.preset;
    form.elements.from.value = state.from;
    form.elements.to.value = state.to;
    form.elements.project.value = state.project;
  };

  async function load() {
    fillProjects();
    if (state.to < state.from) {
      toast('The range must end on or after its first day', 'error');
      return;
    }
    const token = ++loading;
    content.classList.add('is-loading'); // keep the old numbers on screen until the new ones arrive
    const start = `${state.from}T00:00:00`;
    const end = `${dateISO(addDays(parseDay(state.to), 1))}T00:00:00`;
    exportLink.href = api.timeReportXlsxUrl(start, end, projectFilter());
    try {
      const report = await api.timeReport(start, end, projectFilter());
      if (token === loading) {
        content.innerHTML = reportHTML(report);
        tabs.apply();
        tabs.setCounts({ tasks: report.tasks.length || null });
      }
    } catch (err) {
      showError(err);
    } finally {
      if (token === loading) content.classList.remove('is-loading');
    }
  }

  form.addEventListener('change', (e) => {
    if (e.target.name === 'preset') {
      state.preset = e.target.value;
      applyPreset();
    } else if (e.target.name === 'project') {
      state.project = e.target.value;
    } else {
      state.preset = 'custom';
      state.from = form.elements.from.value || state.from;
      state.to = form.elements.to.value || state.to;
    }
    syncForm();
    load();
  });
  form.addEventListener('submit', (e) => e.preventDefault());

  const openRow = (e) => {
    const row = e.target.closest('tr[data-task-id]');
    if (row) openTaskDrawer(Number(row.dataset.taskId));
  };
  content.addEventListener('click', openRow);
  content.addEventListener('keydown', (e) => e.key === 'Enter' && openRow(e));

  fillProjects();
  syncForm();
  await load();
  return { refresh: load };
}
