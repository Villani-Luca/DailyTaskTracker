// Phones show a page's sections one at a time, as tabs. On wider screens CSS hides the
// tab bar and every pane shows in its slot.

import { esc } from '../util.js';

const chosen = new Map(); // view -> the pane last picked there, while the app is open

/** The tab bar. `panes` is a list of [key, label]; mark each section with data-pane="key". */
export function paneTabsHTML(panes) {
  return `<div class="pane-tabs" role="tablist" aria-label="Sections">${panes
    .map(
      ([key, label]) => `<button type="button" role="tab" class="pane-tab" data-pane-tab="${key}">
        ${esc(label)}<span class="count" data-pane-count hidden></span></button>`,
    )
    .join('')}</div>`;
}

/** Wire the tab bar in `root`. Call `apply()` again whenever panes are re-rendered. */
export function bindPaneTabs(root, view, { onShow } = {}) {
  const tabs = [...root.querySelectorAll('[data-pane-tab]')];
  let active = chosen.get(view) ?? tabs[0].dataset.paneTab;

  const apply = () => {
    for (const tab of tabs) {
      const on = tab.dataset.paneTab === active;
      tab.classList.toggle('is-active', on);
      tab.setAttribute('aria-selected', String(on));
    }
    root.querySelectorAll('[data-pane]').forEach((pane) => pane.classList.toggle('is-active', pane.dataset.pane === active));
  };

  root.querySelector('.pane-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('[data-pane-tab]');
    if (!tab || tab.dataset.paneTab === active) return;
    active = tab.dataset.paneTab;
    chosen.set(view, active);
    apply();
    onShow?.(active);
  });
  apply();

  return {
    apply,
    /** Show a number next to some tabs: { key: n }. null hides it. */
    setCounts(counts) {
      for (const tab of tabs) {
        if (!(tab.dataset.paneTab in counts)) continue;
        const n = counts[tab.dataset.paneTab];
        const el = tab.querySelector('[data-pane-count]');
        el.hidden = n == null;
        el.textContent = n ?? '';
      }
    },
  };
}
