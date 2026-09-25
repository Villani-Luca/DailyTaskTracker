// Create or edit a folder. The color picked here is the color of its tasks on the calendar.

import { api } from '../api.js';
import { loadFolders, notifyChange, store } from '../store.js';
import { FOLDER_COLORS, esc, inkOn, showError, toast } from '../util.js';
import { openDialog } from './dialog.js';

function nextFreeColor() {
  const used = new Set(store.folders.map((f) => f.color.toLowerCase()));
  return FOLDER_COLORS.find((c) => !used.has(c)) ?? FOLDER_COLORS[store.folders.length % FOLDER_COLORS.length];
}

/** Resolves with the saved folder, or null if cancelled. */
export function openFolderDialog(folder = null) {
  const initial = folder?.color ?? nextFreeColor();
  const dlg = openDialog({
    title: folder ? 'Edit folder' : 'New folder',
    body: `
      <label class="stacked">Name<input name="name" required maxlength="100" value="${esc(folder?.name ?? '')}" placeholder="e.g. Work, Home, Side project"></label>
      <fieldset class="color-field">
        <legend>Color</legend>
        <div class="swatches">
          ${FOLDER_COLORS.map((c) => `<button type="button" class="swatch-btn" data-color="${c}" style="--c:${c}" aria-label="Color ${c}"></button>`).join('')}
          <label class="custom-color" title="Custom color"><input type="color" name="color" value="${initial}" aria-label="Custom color"></label>
        </div>
        <div class="color-preview" aria-hidden="true">
          <span class="preview-planned">Planned</span>
          <span class="preview-tracked">Time spent</span>
          <span class="muted small">How this folder's tasks look on the calendar</span>
        </div>
      </fieldset>
      <label class="stacked">Description<textarea name="description" rows="2" placeholder="Optional">${esc(folder?.description ?? '')}</textarea></label>
      <footer class="dialog-footer">
        <span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancel</button>
        <button type="submit" class="btn btn-primary">${folder ? 'Save' : 'Create folder'}</button>
      </footer>`,
  });
  const form = dlg.querySelector('form');
  const colorInput = form.elements.color;

  const applyColor = (color) => {
    colorInput.value = color;
    const preview = form.querySelector('.color-preview');
    preview.style.setProperty('--c', color);
    preview.style.setProperty('--c-ink', inkOn(color));
    form.querySelectorAll('.swatch-btn').forEach((b) => b.classList.toggle('is-selected', b.dataset.color === color.toLowerCase()));
  };
  applyColor(initial);
  form.querySelector('.swatches').addEventListener('click', (e) => {
    const btn = e.target.closest('.swatch-btn');
    if (btn) applyColor(btn.dataset.color);
  });
  colorInput.addEventListener('input', () => applyColor(colorInput.value));
  form.elements.name.focus();

  return new Promise((resolve) => {
    let saved = null;
    dlg.addEventListener('close', () => resolve(saved), { once: true });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const data = {
        name: form.elements.name.value.trim(),
        color: colorInput.value,
        description: form.elements.description.value.trim(),
      };
      if (!data.name) {
        toast('The folder needs a name', 'error');
        return;
      }
      try {
        saved = folder ? await api.folders.update(folder.id, data) : await api.folders.create(data);
        await loadFolders();
        dlg.close();
        toast(folder ? 'Folder saved' : 'Folder created');
        notifyChange();
      } catch (err) {
        showError(err);
      }
    });
  });
}
