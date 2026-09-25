// One folder (or the inbox): stats, quick add, filterable task list, edit/delete.

import { api } from '../api.js';
import { confirmDialog } from '../components/dialog.js';
import { openFolderDialog } from '../components/folderDialog.js';
import { kpiHTML } from '../components/kpi.js';
import { statusBarHTML } from '../components/statusBar.js';
import { bindTaskActions, taskListHTML } from '../components/taskList.js';
import { folderById, loadFolders, notifyChange } from '../store.js';
import {
  PRIORITIES, STATUSES, esc, fmtMinutes, icons, setPageTitle, showError, toast,
} from '../util.js';

const INBOX = { id: null, name: 'Inbox', color: '#8a8f98', description: 'Tasks without a folder.' };

function statsHTML(s) {
  const done = s.statuses.find((x) => x.status === 'done')?.count ?? 0;
  return `<section class="card folder-stats">
    <div class="folder-stats-bar">
      <div class="completion">
        <span class="completion-value">${Math.round(s.completion_percent)}%</span>
        <span class="muted">done · ${done} of ${s.total_tasks}</span>
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
      <input name="title" placeholder="Add a task to this folder…" aria-label="Task title" maxlength="200">
      <select name="priority" aria-label="Priority">
        ${PRIORITIES.map((p) => `<option value="${p.value}"${p.value === 'medium' ? ' selected' : ''}>${p.label} priority</option>`).join('')}
      </select>
      <input type="date" name="planned_date" aria-label="Planned for">
      <button class="btn btn-primary" type="submit">${icons.plus}Add task</button>
    </form>
    <div class="toolbar">
      <div class="chips" role="group" aria-label="Filter by status" data-chips></div>
      <input type="search" placeholder="Search tasks…" aria-label="Search tasks" data-search>
    </div>
    <div data-list></div>`;

  const header = root.querySelector('[data-header]');
  const list = root.querySelector('[data-list]');
  const chips = root.querySelector('[data-chips]');
  const form = root.querySelector('.quick-add');

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
    const [stats, folderTasks] = await Promise.all([
      api.folders.stats(),
      api.tasks.list(isInbox ? { inbox: true } : { folder_id: folderId }),
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
