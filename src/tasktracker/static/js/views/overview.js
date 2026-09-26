// Overview: today's plan and schedule, work in progress, overdue tasks, the next days.

import { api } from '../api.js';
import { openBlockDialog } from '../components/blockDialog.js';
import { kpiHTML } from '../components/kpi.js';
import { bindPaneTabs, paneTabsHTML } from '../components/panes.js';
import { bindTaskActions, taskListHTML } from '../components/taskList.js';
import { notifyChange, store } from '../store.js';
import {
  esc, fmtDay, fmtMinutes, fmtTime, icons, relDay, setPageTitle, showError, toast, todayISO,
} from '../util.js';

const DAYS_AHEAD = 6;

function scheduleHTML(blocks) {
  if (!blocks.length) {
    return '<p class="empty">No calendar blocks today. <a href="#/calendar">Open the calendar</a> to plan your day.</p>';
  }
  return `<ul class="schedule">${blocks
    .map((b) => {
      const kind = b.is_running ? 'running' : b.kind;
      const label = b.is_running ? 'Running' : b.kind === 'tracked' ? 'Spent' : 'Planned';
      return `<li><button class="schedule-item" data-block-id="${b.id}" style="--c:${b.color}">
        <span class="sch-time">${fmtTime(b.starts_at)}–${b.ends_at ? fmtTime(b.ends_at) : 'now'}</span>
        <span class="sch-bar kind-${kind}"></span>
        <span class="sch-title">${esc(b.display_title)}</span>
        <span class="kind-tag kind-${kind}">${label}</span>
        <span class="sch-duration">${fmtMinutes(b.duration_minutes)}</span>
      </button></li>`;
    })
    .join('')}</ul>`;
}

function dayHTML(day) {
  const open = day.tasks.filter((t) => t.status !== 'done').length;
  const label = relDay(day.day);
  const date = fmtDay(day.day);
  return `<section class="day-group">
    <header class="day-group-header">
      <strong>${label}</strong>
      <span class="muted small">${label === date ? '' : `${date} · `}${open} open · ${fmtMinutes(day.planned_minutes)} planned</span>
    </header>
    ${taskListHTML(day.tasks, { compact: true }, 'Nothing planned')}
  </section>`;
}

function kpisHTML(data) {
  const today = data.days[0];
  const done = today.tasks.filter((t) => t.status === 'done').length;
  return `
    ${kpiHTML("Today's tasks done", `${done} / ${today.tasks.length}`)}
    ${kpiHTML('Time spent today', fmtMinutes(today.tracked_minutes))}
    ${kpiHTML('Planned today', fmtMinutes(today.planned_minutes))}
    ${kpiHTML('In progress', String(data.active.length))}
    ${kpiHTML('Overdue', String(data.overdue.length), { alert: data.overdue.length > 0 })}`;
}

function render(data) {
  const [today, ...upcoming] = data.days;
  return `
    <section class="card slot pane pane-today" data-pane="today">
      <header class="card-header">
        <h2>Today</h2>
        <span class="muted">${fmtDay(today.day, { weekday: 'long', day: 'numeric', month: 'long' })}</span>
      </header>
      <div class="slot-body">
        ${taskListHTML(today.tasks, { showPlanned: false }, 'Nothing planned for today. Give a task a planned date, or drag it onto the calendar.')}
        <h3 class="subhead">Schedule</h3>
        ${scheduleHTML(today.blocks)}
      </div>
    </section>
    <section class="card slot pane pane-active" data-pane="active">
      <header class="card-header"><h2>In progress</h2><span class="count">${data.active.length}</span></header>
      <div class="slot-body">${taskListHTML(data.active, {}, 'Nothing in progress. Start a timer on a task to begin.')}</div>
    </section>
    <section class="card slot pane pane-overdue" data-pane="overdue">
      <header class="card-header"><h2>Overdue</h2><span class="count">${data.overdue.length}</span></header>
      <div class="slot-body">${taskListHTML(data.overdue, {}, 'Nothing overdue.')}</div>
    </section>
    <section class="card slot pane pane-next" data-pane="next">
      <header class="card-header"><h2>Next days</h2></header>
      <div class="slot-body">${upcoming.map(dayHTML).join('')}</div>
    </section>`;
}

function fillFolderSelect(select) {
  const value = select.value;
  select.innerHTML = `<option value="">Inbox</option>${store.folders
    .map((f) => `<option value="${f.id}">${esc(f.name)}</option>`)
    .join('')}`;
  select.value = store.folders.some((f) => String(f.id) === value) ? value : '';
}

export async function mount(root) {
  setPageTitle('Overview');
  root.innerHTML = `
    <form class="quick-add card" autocomplete="off">
      <input name="title" placeholder="Add a task…" aria-label="Task title" maxlength="200">
      <select name="folder_id" aria-label="Folder"></select>
      <input type="date" name="planned_date" aria-label="Planned for" value="${todayISO()}">
      <button class="btn btn-primary" type="submit">${icons.plus}Add task</button>
    </form>
    <div class="kpi-row kpi-strip" data-kpis></div>
    ${paneTabsHTML([['today', 'Today'], ['active', 'In progress'], ['overdue', 'Overdue'], ['next', 'Next days']])}
    <div class="overview-grid panes" data-content></div>`;

  const form = root.querySelector('.quick-add');
  const kpis = root.querySelector('[data-kpis]');
  const content = root.querySelector('[data-content]');
  const tabs = bindPaneTabs(root, 'overview');
  let blocksById = new Map();

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = form.elements.title.value.trim();
    if (!title) return form.elements.title.focus();
    try {
      await api.tasks.create({
        title,
        folder_id: form.elements.folder_id.value ? Number(form.elements.folder_id.value) : null,
        planned_date: form.elements.planned_date.value || null,
      });
      form.elements.title.value = '';
      toast('Task added');
      notifyChange();
    } catch (err) {
      showError(err);
    }
  });

  bindTaskActions(content);
  content.addEventListener('click', (e) => {
    const item = e.target.closest('[data-block-id]');
    if (item) openBlockDialog({ block: blocksById.get(Number(item.dataset.blockId)) });
  });

  const load = async () => {
    fillFolderSelect(form.elements.folder_id);
    const data = await api.overview(DAYS_AHEAD);
    blocksById = new Map(data.days.flatMap((d) => d.blocks).map((b) => [b.id, b]));
    kpis.innerHTML = kpisHTML(data);
    content.innerHTML = render(data);
    tabs.apply();
    tabs.setCounts({ active: data.active.length || null, overdue: data.overdue.length || null });
  };
  await load();
  return { refresh: load };
}
