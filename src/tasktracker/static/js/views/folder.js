// One folder (or the inbox): stats, quick add, filterable task list, edit/delete.

import { api } from '../api.js';
import { openBlockDialog } from '../components/blockDialog.js';
import { confirmDialog } from '../components/dialog.js';
import { openFolderDialog } from '../components/folderDialog.js';
import { acceptDroppedFiles, openImportDialog } from '../components/importDialog.js';
import { kpiHTML } from '../components/kpi.js';
import { statusBarHTML } from '../components/statusBar.js';
import { bindTaskActions, taskListHTML } from '../components/taskList.js';
import { folderById, loadFolders, notifyChange } from '../store.js';
import {
  PRIORITIES, STATUSES, dateISO, describeRecurrence, esc, fmtMinutes, fmtTime, icons, relDay, setPageTitle,
  showError, toast,
} from '../util.js';

const INBOX = { id: null, name: 'Inbox', color: '#8a8f98', description: 'Tasks without a folder.' };

function statsHTML(s) {
  const done = s.statuses.find((x) => x.status === 'done')?.count ?? 0;
  return `<section class="card folder-stats">
    <div class="folder-stats-bar">
      <div class="completion">
        <span class="completion-value">${Math.round(s.completion_percent)}%</span>
        <span class="muted">done Â· ${done} of ${s.total_tasks}</span>
      </div>
      ${statusBarHTML(s.statuses)}
    </div>
    <div class="kpi-row compact">
      ${kpiHTML('Open', String(s.open_tasks))}
      ${kpiHTML('Overdue', String(s.overdue_tasks), { alert: s.overdue_tasks > 0 })}
      ${kpiHTML('Time spent', fmtMinutes(s.tracked_minutes))}
      ${kpiHTML('Planned', fmtMinutes(s.planned_minutes))}
      ${kpiHTML('Estimated', fmtMinutes(s.estimate_minutes))}
    </div>
  </section>`;
}

function appointmentHTML(a) {
  const b = a.block;
  const meta = [];
  if (b.recurrence) {
    const left = a.upcoming ? ` · ${a.upcoming} of ${a.events} to come` : ` · ${a.events} events`;
    meta.push(`<span>${icons.repeat}${esc(describeRecurrence(b.recurrence, b.starts_at))}${left}</span>`);
  } else if (a.events > 1) {
    meta.push(`<span>${a.events} events</span>`);
  }
  if (b.location) meta.push(`<span class="appt-location">${icons.pin}${esc(b.location)}</span>`);
  if (b.source) meta.push(`<span class="muted">From ${esc(b.source)}</span>`);
  const spent = a.tracked_minutes ? ` · ${fmtMinutes(a.tracked_minutes)} spent` : '';
  return `
    <li><button type="button" class="appt-row" data-block-id="${b.id}">
      <span class="appt-when">
        <strong>${relDay(dateISO(new Date(b.starts_at)))}</strong>
        <span>${fmtTime(b.starts_at)}${b.ends_at ? `–${fmtTime(b.ends_at)}` : ''}</span>
      </span>
      <i class="sch-bar kind-${b.kind}"></i>
      <span class="appt-main">
        <span class="appt-title">${esc(b.display_title)}</span>
        ${meta.length ? `<span class="task-meta">${meta.join('')}</span>` : ''}
      </span>
      <span class="sch-duration">${fmtMinutes(b.duration_minutes)}${spent}</span>
    </button></li>`;
}

function appointmentsHTML(list) {
  const upcoming = list.filter((a) => a.upcoming);
  const past = list.filter((a) => !a.upcoming);
  return `
    <div class="card-header">
      <h2>Appointments</h2>
      <button type="button" class="btn btn-sm" data-action="add-appointment">${icons.plus}Add</button>
      <button type="button" class="btn btn-sm" data-action="import">${icons.upload}Import</button>
    </div>
    ${
      upcoming.length
        ? `<ul class="appt-list">${upcoming.map(appointmentHTML).join('')}</ul>`
        : `<p class="empty">${past.length ? 'Nothing coming up.' : 'No appointments yet. Add one, or import an invite (.ics), an email or a calendar link. You can also drop a file here.'}</p>`
    }
    ${
      past.length
        ? `<details class="appt-past"><summary>Past (${past.length})</summary>
             <ul class="appt-list">${past.map(appointmentHTML).join('')}</ul></details>`
        : ''
    }`;
}

const EMPTY_STATS = {
  total_tasks: 0, open_tasks: 0, overdue_tasks: 0, completion_percent: 0,
  tracked_minutes: 0, planned_minutes: 0, estimate_minutes: 0,
  statuses: STATUSES.map((s) => ({ status: s.value, count: 0, percent: 0 })),
};

export async function mount(root, param) {
  const isInbox = param === 'inbox';
  const folderId = isInbox ? null : Number(param);
  let filter = 'all';
  let search = '';
  let tasks = [];

  root.innerHTML = `
    <div class="folder-header" data-header></div>
    <div data-stats></div>
    <form class="quick-add card" autocomplete="off">
      <input name="title" placeholder="Add a task to this folderâ€¦" aria-label="Task title" maxlength="200">
      <select name="priority" aria-label="Priority">
        ${PRIORITIES.map((p) => `<option value="${p.value}"${p.value === 'medium' ? ' selected' : ''}>${p.label} priority</option>`).join('')}
      </select>
      <input type="date" name="planned_date" aria-label="Planned for">
      <button class="btn btn-primary" type="submit">${icons.plus}Add task</button>
    </form>
    <div class="toolbar">
      <div class="chips" role="group" aria-label="Filter by status" data-chips></div>
      <input type="search" placeholder="Search tasksâ€¦" aria-label="Search tasks" data-search>
    </div>
    <div data-list></div>
    <section class="card appointments" data-appointments></section>`;

  const header = root.querySelector('[data-header]');
  const list = root.querySelector('[data-list]');
  const chips = root.querySelector('[data-chips]');
  const form = root.querySelector('.quick-add');
  const appointmentsEl = root.querySelector('[data-appointments]');
  let pastOpen = false;
  let appointmentBlocks = new Map();

  const renderList = () => {
    const q = search.trim().toLowerCase();
    const visible = tasks.filter(
      (t) => (filter === 'all' || t.status === filter) && (!q || t.title.toLowerCase().includes(q)),
    );
    const counts = Object.fromEntries(STATUSES.map((s) => [s.value, tasks.filter((t) => t.status === s.value).length]));
    chips.innerHTML = [{ value: 'all', label: 'All' }, ...STATUSES]
      .map((s) => {
        const n = s.value === 'all' ? tasks.length : counts[s.value];
        const swatch = s.value === 'all' ? '' : `<i class="swatch st-${s.value}"></i>`;
        return `<button type="button" class="chip${filter === s.value ? ' is-active' : ''}" data-filter="${s.value}" aria-pressed="${filter === s.value}">${swatch}${s.label}<span class="chip-count">${n}</span></button>`;
      })
      .join('');
    list.innerHTML = taskListHTML(
      visible,
      { showFolder: false },
      tasks.length ? 'No tasks match this filter.' : 'No tasks yet. Add the first one above.',
    );
  };

  const load = async () => {
    const folder = isInbox ? INBOX : folderById(folderId);
    if (!folder) {
      setPageTitle('Folder not found');
      root.innerHTML = '<div class="card empty-state"><p>This folder does not exist anymore. <a href="#/projects">Back to projects</a></p></div>';
      return;
    }
    const filter = isInbox ? { inbox: true } : { folder_id: folderId };
    const [stats, folderTasks, appointments] = await Promise.all([
      api.folders.stats(),
      api.tasks.list(filter),
      api.appointments(filter),
    ]);
    tasks = folderTasks;
    setPageTitle(folder.name, folder.color);
    header.innerHTML = `
      <p class="muted">${esc(folder.description || (isInbox ? '' : 'No description.'))}</p>
      <span class="spacer"></span>
      ${
        isInbox
          ? ''
          : `<button class="btn" data-action="edit">${icons.edit}Edit folder</button>
             <button class="btn btn-danger-ghost" data-action="delete">${icons.trash}Delete</button>`
      }`;
    root.querySelector('[data-stats]').innerHTML = statsHTML(
      stats.find((s) => s.folder_id === folderId) ?? EMPTY_STATS,
    );
    renderList();
    appointmentBlocks = new Map(appointments.map((a) => [a.block.id, a.block]));
    appointmentsEl.innerHTML = appointmentsHTML(appointments);
    const details = appointmentsEl.querySelector('.appt-past');
    if (details) {
      details.open = pastOpen;
      details.addEventListener('toggle', () => (pastOpen = details.open));
    }
  };

  chips.addEventListener('click', (e) => {
    const chip = e.target.closest('[data-filter]');
    if (!chip) return;
    filter = chip.dataset.filter;
    renderList();
  });
  root.querySelector('[data-search]').addEventListener('input', (e) => {
    search = e.target.value;
    renderList();
  });
  bindTaskActions(list);

  appointmentsEl.addEventListener('click', (e) => {
    const action = e.target.closest('[data-action]')?.dataset.action;
    const row = e.target.closest('[data-block-id]');
    if (action === 'add-appointment') openBlockDialog({ folderId });
    else if (action === 'import') openImportDialog({ folderId });
    else if (row) openBlockDialog({ block: appointmentBlocks.get(Number(row.dataset.blockId)) });
  });
  acceptDroppedFiles(appointmentsEl, () => ({ folderId }));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = form.elements.title.value.trim();
    if (!title) return form.elements.title.focus();
    try {
      await api.tasks.create({
        title,
        folder_id: folderId,
        priority: form.elements.priority.value,
        planned_date: form.elements.planned_date.value || null,
      });
      form.elements.title.value = '';
      toast('Task added');
      notifyChange();
    } catch (err) {
      showError(err);
    }
  });

  header.addEventListener('click', async (e) => {
    const action = e.target.closest('[data-action]')?.dataset.action;
    const folder = folderById(folderId);
    if (!action || !folder) return;
    try {
      if (action === 'edit') {
        await openFolderDialog(folder);
      } else if (action === 'delete') {
        const n = tasks.length;
        const ok = await confirmDialog(
          `Delete the folder "${folder.name}"?${n ? ` Its ${n} ${n === 1 ? 'task moves' : 'tasks move'} to the Inbox.` : ''}`,
        );
        if (!ok) return;
        await api.folders.remove(folder.id);
        await loadFolders();
        toast('Folder deleted');
        location.hash = '#/projects';
        notifyChange();
      }
    } catch (err) {
      showError(err);
    }
  });

  await load();
  return { refresh: load };
}
