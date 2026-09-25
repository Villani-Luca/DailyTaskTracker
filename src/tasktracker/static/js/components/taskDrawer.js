// Side panel with everything about one task: fields (auto-saved), time, comments.

import { api } from '../api.js';
import { folderName, notifyChange, store } from '../store.js';
import {
  PRIORITIES, STATUSES, addMinutes, dateISO, esc, fmtDateTime, fmtDay, fmtMinutes, fmtTime,
  icons, parseDuration, showError, toast,
} from '../util.js';
import { openBlockDialog } from './blockDialog.js';
import { confirmDialog } from './dialog.js';

const MAX_BLOCKS = 8;
let state = null; // { task, comments, blocks }

const drawerEl = () => document.getElementById('drawer');
const isOpen = () => !drawerEl().hidden;

export async function openTaskDrawer(taskId) {
  try {
    const [task, comments, blocks] = await Promise.all([
      api.tasks.get(taskId),
      api.comments.list(taskId),
      api.tasks.blocks(taskId),
    ]);
    state = { task, comments, blocks };
    render();
    drawerEl().hidden = false;
    drawerEl().querySelector('.title-input').focus();
  } catch (err) {
    showError(err);
  }
}

export function closeTaskDrawer() {
  drawerEl().hidden = true;
  drawerEl().innerHTML = '';
  state = null;
}

/** Re-sync after changes made elsewhere (timer stopped from the top bar, calendar edits…). */
export async function refreshTaskDrawer() {
  if (!state || !isOpen()) return;
  const id = state.task.id;
  try {
    const [task, comments, blocks] = await Promise.all([
      api.tasks.get(id),
      api.comments.list(id),
      api.tasks.blocks(id),
    ]);
    if (state?.task.id !== id) return;
    state = { task, comments, blocks };
    syncFields();
    renderTime();
    renderComments();
  } catch (err) {
    if (err.status === 404) closeTaskDrawer();
    else showError(err);
  }
}

// --- Rendering ---------------------------------------------------------------------

function options(list, selected) {
  return list
    .map((o) => `<option value="${esc(o.value)}"${String(o.value) === String(selected ?? '') ? ' selected' : ''}>${esc(o.label)}</option>`)
    .join('');
}

function render() {
  const { task } = state;
  const folderOptions = [{ value: '', label: 'Inbox' }, ...store.folders.map((f) => ({ value: f.id, label: f.name }))];
  drawerEl().innerHTML = `
    <div class="drawer-backdrop" data-close></div>
    <aside class="drawer-panel" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <header class="drawer-header" style="--c:${task.color}">
        <i class="dot" style="--c:${task.color}"></i>
        <span class="drawer-kicker">${esc(folderName(task.folder_id))} · #${task.id}</span>
        <button class="icon-btn" data-close aria-label="Close">${icons.close}</button>
      </header>
      <div class="drawer-body">
        <textarea id="drawer-title" class="title-input" data-field="title" rows="1" maxlength="200"
          aria-label="Title">${esc(task.title)}</textarea>
        <div class="field-grid">
          <label>Status<select data-field="status">${options(STATUSES, task.status)}</select></label>
          <label>Priority<select data-field="priority">${options(PRIORITIES, task.priority)}</select></label>
          <label>Folder<select data-field="folder_id">${options(folderOptions, task.folder_id)}</select></label>
          <label>Estimate<input data-field="estimate_minutes" placeholder="e.g. 1h 30m"
            value="${task.estimate_minutes ? fmtMinutes(task.estimate_minutes) : ''}"></label>
          <label>Planned for<input type="date" data-field="planned_date" value="${task.planned_date ?? ''}"></label>
          <label>Due<input type="date" data-field="due_date" value="${task.due_date ?? ''}"></label>
        </div>
        <label class="stacked">Description
          <textarea data-field="description" rows="4" placeholder="Details, links, acceptance criteria…">${esc(task.description)}</textarea>
        </label>
        <section class="drawer-section" data-section="time"></section>
        <section class="drawer-section" data-section="comments"></section>
      </div>
      <footer class="drawer-footer">
        <button class="btn btn-danger-ghost" data-action="delete-task">${icons.trash}Delete task</button>
        <span class="muted small">Created ${fmtDateTime(task.created_at)}</span>
      </footer>
    </aside>`;
  renderTime();
  renderComments();
  bind();
  autoGrow(drawerEl().querySelector('.title-input'));
}

function renderTime() {
  const { task, blocks } = state;
  const section = drawerEl().querySelector('[data-section="time"]');
  const est = task.estimate_minutes;
  const ratio = est ? task.tracked_minutes / est : 0;
  const over = est && task.tracked_minutes > est;

  const meter = est
    ? `<div class="meter${over ? ' is-over' : ''}" role="meter" aria-valuemin="0" aria-valuemax="${est}"
          aria-valuenow="${task.tracked_minutes}" aria-label="Tracked time against estimate">
         <span style="width:${Math.min(100, ratio * 100)}%"></span>
       </div>
       <p class="meter-caption">${
         over
           ? `${icons.alert}Over estimate by ${fmtMinutes(task.tracked_minutes - est)}`
           : `${Math.round(ratio * 100)}% of estimate · ${fmtMinutes(est - task.tracked_minutes)} left`
       }</p>`
    : '';

  const rows = blocks.slice(0, MAX_BLOCKS).map((b) => {
    const label = b.is_running ? 'Running' : b.kind === 'tracked' ? 'Spent' : 'Planned';
    const end = b.ends_at ? fmtTime(b.ends_at) : 'now';
    return `<li><button class="block-item" data-block-id="${b.id}">
        <span class="kind-tag kind-${b.is_running ? 'running' : b.kind}">${label}</span>
        <span>${fmtDay(dateISO(new Date(b.starts_at)))} · ${fmtTime(b.starts_at)}–${end}</span>
        <span class="muted">${fmtMinutes(b.duration_minutes)}</span>
      </button></li>`;
  });
  const more = blocks.length > MAX_BLOCKS ? `<li class="muted small">and ${blocks.length - MAX_BLOCKS} more</li>` : '';

  section.innerHTML = `
    <h3>Time</h3>
    <div class="time-summary">
      <div><span class="label">Spent</span><strong>${fmtMinutes(task.tracked_minutes)}</strong></div>
      <div><span class="label">Planned</span><strong>${fmtMinutes(task.planned_minutes)}</strong></div>
      <div><span class="label">Estimate</span><strong>${est ? fmtMinutes(est) : '–'}</strong></div>
    </div>
    ${meter}
    <div class="button-row">
      ${
        task.is_timer_running
          ? `<button class="btn btn-primary" data-action="stop-timer">${icons.stop}Stop timer</button>`
          : `<button class="btn btn-primary" data-action="start-timer">${icons.play}Start timer</button>`
      }
      <button class="btn" data-action="log-time">${icons.clock}Log time</button>
      <button class="btn" data-action="plan-time">${icons.calendar}Plan time</button>
    </div>
    ${blocks.length ? `<ul class="block-list">${rows.join('')}${more}</ul>` : ''}`;
}

function renderComments() {
  const { comments } = state;
  const section = drawerEl().querySelector('[data-section="comments"]');
  const draft = section.querySelector('textarea')?.value ?? '';
  section.innerHTML = `
    <h3>Comments <span class="count">${comments.length}</span></h3>
    ${
      comments.length
        ? `<ul class="comment-list">${comments
            .map(
              (c) => `<li>
                <div class="comment-meta">
                  <span>${fmtDateTime(c.created_at)}</span>
                  <button class="icon-btn sm" data-delete-comment="${c.id}" aria-label="Delete comment" title="Delete comment">${icons.trash}</button>
                </div>
                <p class="comment-body">${esc(c.body)}</p>
              </li>`,
            )
            .join('')}</ul>`
        : '<p class="empty">No comments yet.</p>'
    }
    <form class="comment-form">
      <textarea name="body" rows="2" placeholder="Add a comment… (Ctrl+Enter to post)" aria-label="New comment"></textarea>
      <button class="btn btn-primary" type="submit">Comment</button>
    </form>`;
  section.querySelector('textarea').value = draft;
}

/** Update field values changed elsewhere, without touching the one being edited. */
function syncFields() {
  const { task } = state;
  const values = {
    status: task.status,
    priority: task.priority,
    folder_id: task.folder_id ?? '',
    planned_date: task.planned_date ?? '',
    due_date: task.due_date ?? '',
  };
  for (const [field, value] of Object.entries(values)) {
    const input = drawerEl().querySelector(`[data-field="${field}"]`);
    if (input && input !== document.activeElement) input.value = value;
  }
}

function autoGrow(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = `${textarea.scrollHeight}px`;
}

// --- Behaviour ---------------------------------------------------------------------

async function saveField(input) {
  const field = input.dataset.field;
  let value = input.value;
  if (field === 'title') {
    value = value.trim();
    if (!value) {
      input.value = state.task.title;
      toast('A task needs a title', 'error');
      return;
    }
  } else if (field === 'planned_date' || field === 'due_date') {
    value = value || null;
  } else if (field === 'folder_id') {
    value = value ? Number(value) : null;
  } else if (field === 'estimate_minutes') {
    value = parseDuration(value);
    if (Number.isNaN(value)) {
      toast('Could not read that duration. Try 90, 45m or 1h 30m', 'error');
      return;
    }
  }
  try {
    state.task = await api.tasks.update(state.task.id, { [field]: value });
    if (field === 'estimate_minutes') input.value = value ? fmtMinutes(value) : '';
    if (field === 'folder_id') {
      const header = drawerEl().querySelector('.drawer-header');
      header.querySelector('.dot').style.setProperty('--c', state.task.color);
      header.querySelector('.drawer-kicker').textContent = `${folderName(state.task.folder_id)} · #${state.task.id}`;
    }
    renderTime();
    notifyChange();
  } catch (err) {
    showError(err);
  }
}

async function runAction(action, target) {
  const { task } = state;
  if (action === 'start-timer') {
    await api.timer.start(task.id);
    notifyChange();
  } else if (action === 'stop-timer') {
    await api.timer.stop();
    notifyChange();
  } else if (action === 'log-time' || action === 'plan-time') {
    const tracked = action === 'log-time';
    const minutes = task.estimate_minutes || 60;
    const now = new Date();
    now.setSeconds(0, 0);
    const start = tracked ? addMinutes(now, -minutes) : now;
    openBlockDialog({ taskId: task.id, kind: tracked ? 'tracked' : 'planned', start, end: addMinutes(start, minutes) });
  } else if (action === 'delete-task') {
    const ok = await confirmDialog(`Delete "${task.title}" with its comments and calendar blocks?`);
    if (!ok) return;
    await api.tasks.remove(task.id);
    closeTaskDrawer();
    toast('Task deleted');
    notifyChange();
  } else if (target.dataset.blockId) {
    const block = state.blocks.find((b) => b.id === Number(target.dataset.blockId));
    if (block) openBlockDialog({ block });
  } else if (target.dataset.deleteComment) {
    await api.comments.remove(Number(target.dataset.deleteComment));
    state.comments = state.comments.filter((c) => c.id !== Number(target.dataset.deleteComment));
    renderComments();
    notifyChange();
  }
}

async function postComment(form) {
  const textarea = form.elements.body;
  const body = textarea.value.trim();
  if (!body) return;
  try {
    const comment = await api.comments.add(state.task.id, body);
    textarea.value = '';
    state.comments.push(comment);
    renderComments();
    notifyChange();
  } catch (err) {
    showError(err);
  }
}

function bind() {
  // Listeners go on elements rebuilt by render(), never on the persistent #drawer,
  // so reopening the drawer doesn't stack handlers.
  drawerEl().querySelectorAll('[data-close]').forEach((el) => el.addEventListener('click', closeTaskDrawer));
  const root = drawerEl().querySelector('.drawer-panel');

  root.addEventListener('change', (e) => {
    if (e.target.dataset.field) saveField(e.target);
  });
  root.addEventListener('input', (e) => {
    if (e.target.classList.contains('title-input')) autoGrow(e.target);
  });
  root.addEventListener('keydown', (e) => {
    if (e.target.classList.contains('title-input') && e.key === 'Enter') {
      e.preventDefault();
      e.target.blur();
    }
    if (e.target.name === 'body' && e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      postComment(e.target.form);
    }
  });
  root.addEventListener('submit', (e) => {
    e.preventDefault();
    postComment(e.target);
  });
  root.addEventListener('click', async (e) => {
    const target = e.target.closest('[data-action], [data-block-id], [data-delete-comment]');
    if (!target) return;
    try {
      await runAction(target.dataset.action, target);
    } catch (err) {
      showError(err);
    }
  });
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && isOpen() && !document.querySelector('dialog[open]')) closeTaskDrawer();
});
