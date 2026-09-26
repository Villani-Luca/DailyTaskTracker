// Create or edit a calendar block: a task placed on the calendar, time spent, or an appointment.
// Planned blocks can repeat: every event of a series is a block of its own.

import { api } from '../api.js';
import { folderName, notifyChange, store } from '../store.js';
import {
  WEEKDAYS, addMinutes, addMonths, dateISO, describeRecurrence, esc, icons, showError, toInputDateTime,
  toast,
} from '../util.js';
import { chooseDialog, confirmDialog, openDialog } from './dialog.js';
import { openTaskDrawer } from './taskDrawer.js';

const KIND_HINTS = {
  planned: 'Time you set aside. Shown as a tinted block on the calendar.',
  tracked: 'Time you actually spent. Counts toward the task and folder totals.',
};
const UNITS = { daily: 'days', weekly: 'weeks', monthly: 'months' };
const SCOPES = [
  { value: 'this', label: 'This event' },
  { value: 'following', label: 'This and following events' },
];

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

function repeatHTML(rule, start) {
  const weekdays = rule?.weekdays?.length ? rule.weekdays : [(start.getDay() + 6) % 7];
  const until = rule?.until ?? dateISO(addMonths(start, 3));
  return `
    <label class="stacked">Repeat
      <select name="frequency">
        <option value="">Doesn't repeat</option>
        ${Object.keys(UNITS)
          .map((f) => `<option value="${f}"${rule?.frequency === f ? ' selected' : ''}>${f[0].toUpperCase()}${f.slice(1)}</option>`)
          .join('')}
      </select>
    </label>
    <div class="repeat-details" data-repeat-details>
      <div class="grid-2">
        <label class="stacked">Every
          <span class="inline-field">
            <input type="number" name="interval" min="1" max="99" value="${rule?.interval ?? 1}">
            <span data-unit></span>
          </span>
        </label>
        <label class="stacked">Until<input type="date" name="until" value="${until}"></label>
      </div>
      <fieldset class="weekday-picker" data-weekdays>
        <legend>On</legend>
        ${WEEKDAYS.map(
          (name, i) => `<label><input type="checkbox" name="weekday" value="${i}"${weekdays.includes(i) ? ' checked' : ''}>${esc(name)}</label>`,
        ).join('')}
      </fieldset>
      <p class="hint" data-monthly-hint></p>
    </div>`;
}

/** The repeat rule the form describes, or null. Same shape as the API's. */
function readRule(form) {
  const f = form.elements;
  if (!f.frequency.value || form.querySelector('input[name="kind"]:checked')?.value === 'tracked') return null;
  const weekdays = [...form.querySelectorAll('input[name="weekday"]:checked')].map((i) => Number(i.value));
  return {
    frequency: f.frequency.value,
    interval: Math.max(1, Number(f.interval.value) || 1),
    weekdays: f.frequency.value === 'weekly' ? weekdays : [],
    until: f.until.value,
  };
}

function sameRule(a, b) {
  const key = (r) => r && JSON.stringify([r.frequency, r.interval, [...r.weekdays].sort(), r.until]);
  return key(a) === key(b);
}

/**
 * Edit `block`, or add one. A new one can start prefilled: `title`, `notes` and
 * `folderId` for an appointment (from the folder page, or an email without an invite).
 */
export async function openBlockDialog({
  block = null, start = null, end = null, kind = 'planned', taskId = null, title = '', notes = '', folderId = null,
} = {}) {
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
  const startDate = block ? new Date(block.starts_at) : start;
  const startValue = toInputDateTime(startDate);
  const endValue = toInputDateTime(block?.ends_at ? new Date(block.ends_at) : block ? new Date() : end);
  const folderOptions = store.folders
    .map((f) => `<option value="${f.id}"${f.id === (block ? block.folder_id : folderId) ? ' selected' : ''}>${esc(f.name)}</option>`)
    .join('');
  // Series actions apply to planned events only: time already spent is history.
  const series = block?.kind === 'planned' ? block.recurrence : null;

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
          <input name="title" maxlength="200" placeholder="e.g. Dentist, team meeting" value="${esc(block?.title ?? title)}">
        </label>
        <label class="stacked">Location
          <input name="location" maxlength="500" placeholder="Room, address or meeting link" value="${esc(block?.location ?? '')}">
        </label>
        <label class="stacked">Folder <span class="muted">(sets the color)</span>
          <select name="folder_id"><option value="">Inbox</option>${folderOptions}</select>
        </label>
      </div>
      <div class="grid-2">
        <label class="stacked">Start<input type="datetime-local" name="starts_at" required value="${startValue}"></label>
        <label class="stacked">End<input type="datetime-local" name="ends_at" required value="${endValue}"${running ? ' disabled' : ''}></label>
      </div>
      <div class="repeat-fields" data-repeat>
        ${series ? `<p class="series-note">${icons.repeat}${esc(describeRecurrence(series, block.starts_at))}. Dragging on the calendar moves one event only.</p>` : ''}
        ${repeatHTML(series, startDate)}
      </div>
      <label class="stacked">Notes<textarea name="notes" rows="${(block?.notes ?? notes).length > 120 ? 5 : 2}">${esc(block?.notes ?? notes)}</textarea></label>
      ${block?.source ? `<p class="hint">Imported from ${esc(block.source)}</p>` : ''}
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
  const f = form.elements;
  const appointment = form.querySelector('[data-appointment]');
  const repeat = form.querySelector('[data-repeat]');
  const kindValue = () => form.querySelector('input[name="kind"]:checked')?.value ?? currentKind;

  const syncAppointment = () => {
    appointment.hidden = Boolean(f.task_id.value);
  };
  const syncRepeat = () => {
    repeat.hidden = running || kindValue() === 'tracked';
    const frequency = f.frequency.value;
    form.querySelector('[data-repeat-details]').hidden = !frequency;
    form.querySelector('[data-weekdays]').hidden = frequency !== 'weekly';
    form.querySelector('[data-unit]').textContent = UNITS[frequency] ?? '';
    const day = f.starts_at.value ? new Date(f.starts_at.value).getDate() : null;
    form.querySelector('[data-monthly-hint]').textContent =
      frequency === 'monthly' && day
        ? `On day ${day} of the month.${day > 28 ? ' Months without that day are skipped.' : ''}`
        : '';
  };
  syncAppointment();
  syncRepeat();
  f.task_id.addEventListener('change', syncAppointment);
  form.addEventListener('change', (e) => {
    if (e.target.name === 'kind') form.querySelector('[data-kind-hint]').textContent = KIND_HINTS[e.target.value];
    syncRepeat();
  });

  // Weekly on the start's weekday: moving the start to another day moves the weekday along.
  let startWeekday = (startDate.getDay() + 6) % 7;
  f.starts_at.addEventListener('change', () => {
    if (!f.starts_at.value) return;
    const weekday = (new Date(f.starts_at.value).getDay() + 6) % 7;
    const checked = [...form.querySelectorAll('input[name="weekday"]:checked')];
    if (checked.length === 1 && Number(checked[0].value) === startWeekday) {
      checked[0].checked = false;
      form.querySelector(`input[name="weekday"][value="${weekday}"]`).checked = true;
    }
    startWeekday = weekday;
    syncRepeat();
  });

  const done = (message) => {
    dlg.close();
    toast(message);
    notifyChange();
  };

  /** Which events a save applies to; null when cancelled. */
  async function saveScope(rule) {
    if (!series || kindValue() === 'tracked') return 'this';
    if (sameRule(rule, series)) return chooseDialog('Save the changes to', SCOPES, { confirmLabel: 'Save' });
    const message = rule
      ? 'The new repeat applies to this and the following events.'
      : 'Stop repeating after this event? The following events are deleted.';
    return (await confirmDialog(message, { confirmLabel: rule ? 'Save' : 'Stop repeating', danger: !rule }))
      ? 'following'
      : null;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
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
    const rule = readRule(form);
    if (rule && !rule.until) {
      toast('Pick the day the repeat ends', 'error');
      f.until.focus();
      return;
    }
    if (rule?.frequency === 'weekly' && !rule.weekdays.length) {
      toast('Pick at least one day of the week', 'error');
      return;
    }
    const payload = {
      task_id: linkedTask,
      title: linkedTask ? '' : title,
      folder_id: linkedTask || !f.folder_id.value ? null : Number(f.folder_id.value),
      location: linkedTask ? '' : f.location.value.trim(),
      starts_at: f.starts_at.value,
      notes: f.notes.value,
    };
    if (!running) {
      payload.kind = kindValue();
      payload.ends_at = f.ends_at.value;
    }
    try {
      if (block) {
        const scope = await saveScope(rule);
        if (!scope) return;
        const ruleChanged = !sameRule(rule, series);
        if (ruleChanged && (scope === 'following' || !series)) payload.recurrence = rule;
        await api.blocks.update(block.id, payload, scope);
        done('Saved');
      } else {
        if (rule) payload.recurrence = rule;
        await api.blocks.create(payload);
        done(rule ? 'Added the repeating events' : 'Added to calendar');
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
        let scope = 'this';
        if (series) {
          scope = await chooseDialog('Delete', [...SCOPES, { value: 'all', label: 'All events' }], {
            confirmLabel: 'Delete',
            danger: true,
          });
          if (!scope) return;
        } else if (!(await confirmDialog('Delete this calendar block?'))) {
          return;
        }
        await api.blocks.remove(block.id, scope);
        done(scope === 'this' ? 'Block deleted' : 'Events deleted');
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
