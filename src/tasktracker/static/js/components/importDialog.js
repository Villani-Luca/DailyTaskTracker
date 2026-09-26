// Import appointments from an .ics file, an email (.eml), pasted text or a calendar link.
// Two steps: read the source and preview its events, then import the picked ones into a
// folder. An email without an invite opens a new appointment with its subject and text.

import { api } from '../api.js';
import { folderName, notifyChange, store } from '../store.js';
import {
  addDays, dateISO, describeRecurrence, esc, fmtDateTime, fmtDay, fmtTime, icons, showError, toast,
} from '../util.js';
import { openBlockDialog } from './blockDialog.js';
import { openDialog } from './dialog.js';

const MAX_BYTES = 5_000_000;
const ACCEPT = '.ics,.ical,.vcs,.eml,text/calendar,message/rfc822';
const STATUS_TAG = { new: 'New', update: 'Updates', cancel: 'Cancels' };
const WAYS = [
  { value: 'file', label: 'File' },
  { value: 'paste', label: 'Paste' },
  { value: 'link', label: 'Link' },
];

/** True when a drag carries files (not a task or a calendar block). */
export function isFileDrag(e) {
  return [...(e.dataTransfer?.types ?? [])].includes('Files');
}

/** Let files dropped on `el` open the import dialog. */
export function acceptDroppedFiles(el, options = () => ({})) {
  el.addEventListener('dragover', (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    el.classList.add('is-dropping');
  });
  el.addEventListener('dragleave', (e) => {
    if (!el.contains(e.relatedTarget)) el.classList.remove('is-dropping');
  });
  el.addEventListener('drop', (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    el.classList.remove('is-dropping');
    const file = e.dataTransfer.files[0];
    if (file) openImportDialog({ ...options(), file });
  });
}

export function openImportDialog({ folderId = null, file = null } = {}) {
  const state = { folderId, way: 'file', file, text: '', url: '' };
  showSourceStep(state);
  if (file) readAndPreview(state);
}

// --- Step 1: where the appointments come from ---------------------------------------

function showSourceStep(state) {
  const dlg = openDialog({
    title: 'Import appointments',
    className: 'import-dialog',
    body: `
      <div class="segmented" role="radiogroup" aria-label="Import from">
        ${WAYS.map((w) => `<label><input type="radio" name="way" value="${w.value}"${state.way === w.value ? ' checked' : ''}>${w.label}</label>`).join('')}
      </div>
      <div data-way="file">
        <label class="drop-zone" data-drop>
          <input type="file" name="file" accept="${ACCEPT}">
          ${icons.upload}
          <span data-file-label>${state.file ? esc(state.file.name) : 'Drop an <strong>.ics</strong> invite or a saved email (<strong>.eml</strong>) here, or <u>choose a file</u>'}</span>
        </label>
        <p class="hint">Save the invite attached to an email (<em>invite.ics</em>), export a calendar,
          or save the whole email: in Gmail <em>⋮ › Download message</em>, in Outlook drag it to the desktop.</p>
      </div>
      <div data-way="paste">
        <label class="stacked">Invite, email or text
          <textarea name="text" rows="7" placeholder="Paste an invite (BEGIN:VCALENDAR…), the source of an email, or just some text">${esc(state.text)}</textarea>
        </label>
        <p class="hint">Text without an invite starts a new appointment with it, for you to set the time.</p>
      </div>
      <div data-way="link">
        <label class="stacked">Calendar link
          <input type="url" name="url" placeholder="https://… or webcal://…" value="${esc(state.url)}">
        </label>
        <p class="hint">A calendar's iCal address: in Google Calendar <em>Settings › Integrate calendar</em>,
          in Outlook <em>Settings › Shared calendars › Publish</em>. It is read once; import again to update.</p>
      </div>
      <footer class="dialog-footer">
        <span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancel</button>
        <button type="submit" class="btn btn-primary">Preview</button>
      </footer>`,
  });

  const form = dlg.querySelector('form');
  const f = form.elements;
  const sync = () => {
    form.querySelectorAll('[data-way]').forEach((el) => (el.hidden = el.dataset.way !== state.way));
  };
  sync();
  form.addEventListener('change', (e) => {
    if (e.target.name === 'way') {
      state.way = e.target.value;
      sync();
      (state.way === 'paste' ? f.text : state.way === 'link' ? f.url : null)?.focus();
    } else if (e.target.name === 'file' && e.target.files[0]) {
      state.file = e.target.files[0];
      readAndPreview(state);
    }
  });
  const drop = form.querySelector('[data-drop]');
  drop.addEventListener('dragover', (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    drop.classList.add('is-dropping');
  });
  drop.addEventListener('dragleave', () => drop.classList.remove('is-dropping'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('is-dropping');
    if (!e.dataTransfer.files[0]) return;
    state.file = e.dataTransfer.files[0];
    readAndPreview(state);
  });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    state.text = f.text.value;
    state.url = f.url.value.trim();
    readAndPreview(state);
  });
}

async function sourceOf(state) {
  if (state.way === 'link') {
    if (!state.url) throw new Error('Paste the calendar link');
    return { url: state.url };
  }
  if (state.way === 'paste') {
    if (!state.text.trim()) throw new Error('Paste an invite, an email or some text');
    return { content: state.text, filename: '' };
  }
  if (!state.file) throw new Error('Choose a file');
  if (state.file.size > MAX_BYTES) throw new Error('That file is too big (more than 5 MB)');
  return { content: await state.file.text(), filename: state.file.name };
}

async function readAndPreview(state) {
  const dlg = document.getElementById('dialog');
  const submit = dlg.querySelector('button[type="submit"]');
  if (submit) {
    submit.disabled = true;
    submit.textContent = 'Reading…';
  }
  try {
    const source = await sourceOf(state);
    const preview = await api.imports.preview(source);
    if (!preview.events.length && preview.draft) {
      dlg.close();
      openBlockDialog({
        title: preview.draft.title,
        notes: preview.draft.notes,
        folderId: state.folderId,
      });
      toast('No invite found: set the time of the new appointment');
      return;
    }
    showPreviewStep(state, source, preview);
  } catch (err) {
    showError(err);
    if (submit) {
      submit.disabled = false;
      submit.textContent = 'Preview';
    }
  }
}

// --- Step 2: what the import does ----------------------------------------------------

function whenHTML(ev) {
  if (ev.all_day) {
    const last = addDays(new Date(ev.ends_at), -1);
    const first = fmtDay(ev.starts_at.slice(0, 10));
    const range = dateISO(last) > ev.starts_at.slice(0, 10) ? `${first} – ${fmtDay(dateISO(last))}` : first;
    return `${range} · all day, added as a task`;
  }
  return `${fmtDateTime(ev.starts_at)}–${fmtTime(ev.ends_at)}`;
}

function eventRowHTML(ev, checked, includePast) {
  const count = ev.events + (includePast ? ev.past_events : 0);
  const meta = [];
  if (ev.recurrence) {
    meta.push(`<span>${icons.repeat}${esc(describeRecurrence(ev.recurrence, ev.starts_at))}</span>`);
  }
  if (ev.status !== 'cancel' && (ev.recurrence || ev.past_events)) {
    meta.push(`<span>${count} ${count === 1 ? 'event' : 'events'}${
      ev.past_events && !includePast ? ` (${ev.past_events} past skipped)` : ''}</span>`);
  }
  if (ev.location) meta.push(`<span>${icons.pin}${esc(ev.location)}</span>`);
  if (ev.organizer) meta.push(`<span>${esc(ev.organizer)}</span>`);
  return `
    <label class="import-row${count || ev.status === 'cancel' ? '' : ' is-empty'}">
      <input type="checkbox" name="key" value="${esc(ev.key)}"${checked ? ' checked' : ''}>
      <span class="import-main">
        <span class="import-title">${esc(ev.title)}
          <span class="kind-tag status-${ev.status}">${STATUS_TAG[ev.status]}</span></span>
        <span class="import-when">${whenHTML(ev)}</span>
        ${meta.length ? `<span class="import-meta">${meta.join('')}</span>` : ''}
        ${ev.warnings.map((w) => `<span class="import-warning">${icons.alert}${esc(w)}</span>`).join('')}
      </span>
    </label>`;
}

function showPreviewStep(state, source, preview) {
  let includePast = false;
  // Nothing to add (it's all in the past): not picked unless past events are wanted.
  const useful = (ev) => ev.status === 'cancel' || ev.events + (includePast ? ev.past_events : 0) > 0;
  const picked = new Set(preview.events.filter(useful).map((ev) => ev.key));
  const folderOptions = store.folders
    .map((fo) => `<option value="${fo.id}"${fo.id === state.folderId ? ' selected' : ''}>${esc(fo.name)}</option>`)
    .join('');
  const anyPast = preview.events.some((ev) => ev.past_events);

  const dlg = openDialog({
    title: 'Import appointments',
    className: 'import-dialog',
    body: `
      <p class="series-note">${icons.calendar}<span>From <strong>${esc(preview.source)}</strong>: ${preview.events.length} ${preview.events.length === 1 ? 'event' : 'events'}</span></p>
      ${preview.warnings.map((w) => `<p class="import-warning">${icons.alert}${esc(w)}</p>`).join('')}
      <label class="stacked">Folder <span class="muted">(every event goes in it, repeating ones included)</span>
        <select name="folder_id"><option value="">Inbox</option>${folderOptions}</select>
      </label>
      <div class="import-toolbar">
        <label class="toggle"><input type="checkbox" data-all>Select all</label>
        ${anyPast ? '<label class="toggle"><input type="checkbox" name="include_past">Include past events</label>' : ''}
      </div>
      <div class="import-list" data-list></div>
      <footer class="dialog-footer">
        <button type="button" class="btn" data-action="back">Back</button>
        <span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancel</button>
        <button type="submit" class="btn btn-primary" data-import>Import</button>
      </footer>`,
  });

  const form = dlg.querySelector('form');
  const list = form.querySelector('[data-list]');
  const all = form.querySelector('[data-all]');
  const importBtn = form.querySelector('[data-import]');

  const render = () => {
    list.innerHTML = preview.events.length
      ? preview.events.map((ev) => eventRowHTML(ev, picked.has(ev.key), includePast)).join('')
      : '<p class="empty">No events to import.</p>';
    all.checked = preview.events.length > 0 && picked.size === preview.events.length;
    all.indeterminate = picked.size > 0 && picked.size < preview.events.length;
    importBtn.disabled = picked.size === 0;
    importBtn.textContent = picked.size ? `Import ${picked.size}` : 'Import';
  };
  render();

  form.addEventListener('change', (e) => {
    if (e.target.name === 'key') {
      if (e.target.checked) picked.add(e.target.value);
      else picked.delete(e.target.value);
    } else if (e.target === all) {
      picked.clear();
      if (all.checked) preview.events.forEach((ev) => picked.add(ev.key));
    } else if (e.target.name === 'include_past') {
      includePast = e.target.checked;
      for (const ev of preview.events) {
        if (!ev.events && ev.past_events) {
          if (includePast) picked.add(ev.key);
          else picked.delete(ev.key);
        }
      }
    } else {
      return;
    }
    render();
  });

  form.querySelector('[data-action="back"]').addEventListener('click', () => showSourceStep(state));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!picked.size) return;
    const folderId = form.elements.folder_id.value ? Number(form.elements.folder_id.value) : null;
    importBtn.disabled = true;
    importBtn.textContent = 'Importing…';
    try {
      const result = await api.imports.run({
        ...source,
        folder_id: folderId,
        keys: [...picked],
        include_past: includePast,
      });
      dlg.close();
      toast(summary(result, folderName(folderId)));
      notifyChange();
    } catch (err) {
      showError(err);
      render();
    }
  });
}

function summary(result, folder) {
  const parts = [];
  if (result.added) parts.push(`${result.added} added`);
  if (result.updated) parts.push(`${result.updated} updated`);
  if (result.cancelled) parts.push(`${result.cancelled} cancelled`);
  if (!parts.length) return 'Nothing to import';
  const tasks = result.tasks ? ` (all-day events as tasks)` : '';
  return `${folder}: ${parts.join(', ')}${tasks}`;
}
