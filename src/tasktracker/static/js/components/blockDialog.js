// Create or edit a calendar block: a task placed on the calendar, time spent, or an appointment.

import { api } from '../api.js';
import { folderName, notifyChange, store } from '../store.js';
import { addMinutes, esc, showError, toInputDateTime, toast } from '../util.js';
import { confirmDialog, openDialog } from './dialog.js';
import { openTaskDrawer } from './taskDrawer.js';

const KIND_HINTS = {
  planned: 'Time you set aside. Shown as a tinted block on the calendar.',
  tracked: 'Time you actually spent. Counts toward the task and folder totals.',
};

function taskOptions(tasks, selectedId) {
  const groups = new Map();
  for (const t of tasks) {
    const key = folderName(t.folder_id);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(t);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(
      ([name, list]) => `<optgroup label="${esc(name)}">${list
        .map((t) => `<option value="${t.id}"${t.id === selectedId ? ' selected' : ''}>${esc(t.title)}</option>`)
        .join('')}</optgroup>`,
    )
    .join('');
}

export async function openBlockDialog({ block = null, start = null, end = null, kind = 'planned', taskId = null } = {}) {
  let tasks;
  try {
    tasks = await api.tasks.list();
  } catch (err) {
    showError(err);
    return;
  }
  if (!block && !start) {
    start = new Date();
    start.setMinutes(0, 0, 0);
  }
  if (!block && !end) end = addMinutes(start, 60);
  const linkedId = block ? block.task_id : taskId;
  const selectable = tasks.filter((t) => t.status !== 'done' || t.id === linkedId);
  const running = block?.is_running ?? false;
  const currentKind = block?.kind ?? kind;
  const startValue = toInputDateTime(block ? new Date(block.starts_at) : start);
  const endValue = toInputDateTime(block?.ends_at ? new Date(block.ends_at) : block ? new Date() : end);
  const folderOptions = store.folders
    .map((f) => `<option value="${f.id}"${f.id === block?.folder_id ? ' selected' : ''}>${esc(f.name)}</option>`)
    .join('');

  const dlg = openDialog({
    title: block ? 'Edit calendar block' : 'Add to calendar',
    body: `
      <div class="segmented" role="radiogroup" aria-label="Kind">
        <label><input type="radio" name="kind" value="planned"${currentKind === 'planned' ? ' checked' : ''}${running ? ' disabled' : ''}>Planned</label>
        <label><input type="radio" name="kind" value="tracked"${currentKind === 'tracked' ? ' checked' : ''}${running ? ' disabled' : ''}>Time spent</label>
      </div>
      <p class="hint" data-kind-hint>${running ? 'Timer running. Stop it from the top bar.' : KIND_HINTS[currentKind]}</p>
      <label class="stacked">Task
        <select name="task_id">
          <option value="">No task (appointment)</option>
          ${taskOptions(selectable, linkedId)}
        </select>
      </label>
      <div class="appointment-fields" data-appointment>
        <label class="stacked">Title
          <input name="title" maxlength="200" placeholder="e.g. Dentist, team meeting" value="${esc(block?.title ?? '')}">
        </label>
        <label class="stacked">Folder <span class="muted">(sets the color)</span>
          <select name="folder_id"><option value="">Inbox</option>${folderOptions}</select>
        </label>
      </div>
      <div class="grid-2">
        <label class="stacked">Start<input type="datetime-local" name="starts_at" required value="${startValue}"></label>
        <label class="stacked">End<input type="datetime-local" name="ends_at" required value="${endValue}"${running ? ' disabled' : ''}></label>
      </div>
      <label class="stacked">Notes<textarea name="notes" rows="2">${esc(block?.notes ?? '')}</textarea></label>
      <footer class="dialog-footer">
        ${block ? '<button type="button" class="btn btn-danger-ghost" data-action="delete">Delete</button>' : ''}
        ${block?.kind === 'planned' ? '<button type="button" class="btn" data-action="spent" title="I spent this time: turn it into tracked time">Mark as spent</button>' : ''}
        ${block?.task_id ? '<button type="button" class="btn" data-action="open-task">Open task</button>' : ''}
        <span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancel</button>
        <button type="submit" class="btn btn-primary">${block ? 'Save' : 'Add'}</button>
      </footer>`,
  });

  const form = dlg.querySelector('form');
  const appointment = form.querySelector('[data-appointment]');
  const syncAppointment = () => {
    appointment.hidden = Boolean(form.elements.task_id.value);
  };
  syncAppointment();
  form.elements.task_id.addEventListener('change', syncAppointment);
  form.addEventListener('change', (e) => {
    if (e.target.name === 'kind') form.querySelector('[data-kind-hint]').textContent = KIND_HINTS[e.target.value];
  });

  const done = (message) => {
    dlg.close();
    toast(message);
    notifyChange();
  };

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = form.elements;
    const linkedTask = f.task_id.value ? Number(f.task_id.value) : null;
    const title = f.title.value.trim();
    if (!linkedTask && !title) {
      toast('Pick a task, or give the appointment a title', 'error');
      f.title.focus();
      return;
    }
    if (!f.starts_at.value || (!running && !f.ends_at.value)) {
      toast('Start and end are required', 'error');
      return;
    }
    const payload = {
      task_id: linkedTask,
      title: linkedTask ? '' : title,
      folder_id: linkedTask || !f.folder_id.value ? null : Number(f.folder_id.value),
      starts_at: f.starts_at.value,
      notes: f.notes.value,
    };
    if (!running) {
      payload.kind = form.querySelector('input[name="kind"]:checked').value;
      payload.ends_at = f.ends_at.value;
    }
    try {
      if (block) {
        await api.blocks.update(block.id, payload);
        done('Saved');
      } else {
        await api.blocks.create(payload);
        done('Added to calendar');
      }
    } catch (err) {
      showError(err);
    }
  });

  form.addEventListener('click', async (e) => {
    const action = e.target.closest('[data-action]')?.dataset.action;
    if (!action) return;
    try {
      if (action === 'delete') {
        if (!(await confirmDialog('Delete this calendar block?'))) return;
        await api.blocks.remove(block.id);
        done('Block deleted');
      } else if (action === 'spent') {
        await api.blocks.update(block.id, { kind: 'tracked' });
        done('Marked as time spent');
      } else if (action === 'open-task') {
        dlg.close();
        openTaskDrawer(block.task_id);
      }
    } catch (err) {
      showError(err);
    }
  });
}
