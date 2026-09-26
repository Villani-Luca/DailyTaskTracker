// Modal dialogs on top of the native <dialog> element.

import { esc, icons } from '../util.js';

/** Open the shared dialog with a form body; the caller wires up the form. */
export function openDialog({ title, body, className = '' }) {
  const dlg = document.getElementById('dialog');
  dlg.className = className;
  dlg.innerHTML = `
    <form class="dialog-form" novalidate>
      <header class="dialog-header">
        <h2>${esc(title)}</h2>
        <button type="button" class="icon-btn" data-close aria-label="Close">${icons.close}</button>
      </header>
      <div class="dialog-body">${body}</div>
    </form>`;
  dlg.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => dlg.close()));
  dlg.showModal();
  return dlg;
}

/** Ask which option applies; resolves to the chosen value, or null if cancelled. */
export function chooseDialog(message, choices, { confirmLabel = 'OK', danger = false } = {}) {
  const dlg = document.getElementById('confirm');
  dlg.innerHTML = `
    <form method="dialog" class="dialog-form">
      <div class="dialog-body">
        <p class="confirm-message">${esc(message)}</p>
        <div class="choice-list">${choices
          .map(
            (c, i) => `<label class="choice"><input type="radio" name="choice" value="${esc(c.value)}"${
              i === 0 ? ' checked' : ''
            }>${esc(c.label)}</label>`,
          )
          .join('')}</div>
      </div>
      <footer class="dialog-footer">
        <span class="spacer"></span>
        <button value="cancel" class="btn">Cancel</button>
        <button value="ok" class="btn ${danger ? 'btn-danger' : 'btn-primary'}">${esc(confirmLabel)}</button>
      </footer>
    </form>`;
  dlg.returnValue = '';
  dlg.showModal();
  const form = dlg.querySelector('form');
  return new Promise((resolve) => {
    dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok' ? form.elements.choice.value : null), {
      once: true,
    });
  });
}

/** Ask for confirmation; resolves to true when confirmed. */
export function confirmDialog(message, { confirmLabel = 'Delete', danger = true } = {}) {
  const dlg = document.getElementById('confirm');
  dlg.innerHTML = `
    <form method="dialog" class="dialog-form">
      <div class="dialog-body"><p class="confirm-message">${esc(message)}</p></div>
      <footer class="dialog-footer">
        <span class="spacer"></span>
        <button value="cancel" class="btn">Cancel</button>
        <button value="ok" class="btn ${danger ? 'btn-danger' : 'btn-primary'}">${esc(confirmLabel)}</button>
      </footer>
    </form>`;
  dlg.returnValue = '';
  dlg.showModal();
  return new Promise((resolve) => {
    dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true });
  });
}
