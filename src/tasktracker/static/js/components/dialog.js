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
