// Task rows shared by every view, with delegated actions (done, timer, open).

import { api } from '../api.js';
import { folderName, notifyChange } from '../store.js';
import { STATUS_LABEL, esc, fmtDay, fmtMinutes, icons, relDay, showError, todayISO, toast } from '../util.js';
import { openTaskDrawer } from './taskDrawer.js';

export function taskRowHTML(task, { showFolder = true, showPlanned = true, compact = false } = {}) {
  const done = task.status === 'done';
  const today = todayISO();
  const meta = [];
  if (compact) {
    showFolder = false;
    showPlanned = false;
  }

  if (showFolder) {
    meta.push(`<span class="meta-folder"><i class="dot" style="--c:${task.color}"></i>${esc(folderName(task.folder_id))}</span>`);
  }
  if (task.status === 'in_progress' || task.status === 'blocked') {
    meta.push(`<span class="status-pill st-${task.status}">${STATUS_LABEL[task.status]}</span>`);
  }
  if (task.priority === 'high' && !done) {
    meta.push(`<span class="meta-prio">${icons.flag}High</span>`);
  }
  if (showPlanned && task.planned_date) {
    const late = !done && task.planned_date < today;
    meta.push(`<span class="${late ? 'meta-late' : ''}">${icons.calendar}${relDay(task.planned_date)}</span>`);
  }
  if (task.due_date) {
    const late = !done && task.due_date < today;
    meta.push(`<span class="${late ? 'meta-late' : ''}">${late ? icons.alert : ''}Due ${fmtDay(task.due_date)}</span>`);
  }
  if (task.tracked_minutes || task.estimate_minutes) {
    const est = task.estimate_minutes ? ` / ${fmtMinutes(task.estimate_minutes)}` : '';
    meta.push(`<span>${icons.clock}${fmtMinutes(task.tracked_minutes)}${est}</span>`);
  }
  if (task.comment_count) {
    meta.push(`<span>${icons.comment}${task.comment_count}</span>`);
  }

  let timer = '';
  if (!compact && task.is_timer_running) {
    timer = `<button class="icon-btn timer-btn is-running" data-action="stop-timer" title="Stop timer" aria-label="Stop timer">${icons.stop}</button>`;
  } else if (!compact && !done) {
    timer = `<button class="icon-btn timer-btn" data-action="start-timer" title="Start timer" aria-label="Start timer">${icons.play}</button>`;
  }

  return `
    <div class="task-row${done ? ' is-done' : ''}${compact ? ' is-compact' : ''}" data-task-id="${task.id}" tabindex="0" style="--c:${task.color}">
      <button class="check" data-action="toggle-done" role="checkbox" aria-checked="${done}"
        aria-label="${done ? 'Mark as not done' : 'Mark as done'}" title="${done ? 'Mark as not done' : 'Mark as done'}">${icons.check}</button>
      <div class="task-main">
        <div class="task-title">${esc(task.title)}</div>
        ${meta.length && !compact ? `<div class="task-meta">${meta.join('')}</div>` : ''}
      </div>
      ${timer}
    </div>`;
}

export function taskListHTML(tasks, options = {}, emptyText = 'Nothing here.') {
  if (!tasks.length) return `<p class="empty">${esc(emptyText)}</p>`;
  return `<div class="task-list">${tasks.map((t) => taskRowHTML(t, options)).join('')}</div>`;
}

/** Wire clicks and keyboard on every task row inside `root`. */
export function bindTaskActions(root) {
  root.addEventListener('click', async (e) => {
    const row = e.target.closest('.task-row');
    if (!row) return;
    const id = Number(row.dataset.taskId);
    const action = e.target.closest('[data-action]')?.dataset.action;
    try {
      if (action === 'toggle-done') {
        const wasDone = row.classList.contains('is-done');
        await api.tasks.update(id, { status: wasDone ? 'todo' : 'done' });
        toast(wasDone ? 'Task reopened' : 'Task done');
        notifyChange();
      } else if (action === 'start-timer') {
        await api.timer.start(id);
        notifyChange();
      } else if (action === 'stop-timer') {
        await api.timer.stop();
        notifyChange();
      } else {
        openTaskDrawer(id);
      }
    } catch (err) {
      showError(err);
    }
  });
  root.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.classList?.contains('task-row')) {
      openTaskDrawer(Number(e.target.dataset.taskId));
    }
  });
}
