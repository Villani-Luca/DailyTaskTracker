// Stacked status bar (part-to-whole of a folder's tasks) with its legend.
// The legend lists every status with count and percent, so no value is hover-only.

import { STATUS_BAR_ORDER, STATUS_LABEL, esc } from '../util.js';

const pct = (p) => `${Math.round(p)}%`;
const tasksWord = (n) => `${n} ${n === 1 ? 'task' : 'tasks'}`;

export function statusBarHTML(statuses, { legend = true } = {}) {
  const byStatus = Object.fromEntries(statuses.map((s) => [s.status, s]));
  const ordered = STATUS_BAR_ORDER.map((key) => byStatus[key]).filter(Boolean);
  const total = ordered.reduce((n, s) => n + s.count, 0);
  const summary = total
    ? ordered.map((s) => `${STATUS_LABEL[s.status]} ${s.count}`).join(', ')
    : 'No tasks yet';

  const segments = ordered
    .filter((s) => s.count > 0)
    .map(
      (s) => `<span class="seg st-${s.status}" style="flex:${s.count} 1 0" tabindex="0"
        data-tip-value="${esc(`${tasksWord(s.count)} · ${pct(s.percent)}`)}"
        data-tip-label="${esc(STATUS_LABEL[s.status])}"
        aria-label="${esc(`${STATUS_LABEL[s.status]}: ${tasksWord(s.count)}, ${pct(s.percent)}`)}"></span>`,
    )
    .join('');

  const bar = `<div class="status-bar${total ? '' : ' is-empty'}" role="group" aria-label="${esc(summary)}">${segments}</div>`;
  if (!legend) return bar;

  const items = ordered
    .map(
      (s) => `<li>
        <i class="swatch st-${s.status}"></i>
        <span class="lg-label">${STATUS_LABEL[s.status]}</span>
        <span class="lg-count">${s.count}</span>
        <span class="lg-pct">${total ? pct(s.percent) : '–'}</span>
      </li>`,
    )
    .join('');
  return `${bar}<ul class="status-legend">${items}</ul>`;
}

/** One shared tooltip for every element carrying data-tip-value / data-tip-label. */
export function installTooltips() {
  const tip = document.getElementById('tooltip');
  let anchor = null;

  const show = (el) => {
    anchor = el;
    tip.innerHTML = `<strong>${esc(el.dataset.tipValue)}</strong><span>${esc(el.dataset.tipLabel ?? '')}</span>`;
    tip.hidden = false;
    const r = el.getBoundingClientRect();
    const t = tip.getBoundingClientRect();
    const left = Math.min(Math.max(8, r.left + r.width / 2 - t.width / 2), innerWidth - t.width - 8);
    const top = r.top - t.height - 8 < 8 ? r.bottom + 8 : r.top - t.height - 8;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  };
  const hide = (el) => {
    if (el === anchor) {
      tip.hidden = true;
      anchor = null;
    }
  };
  const target = (e) => e.target.closest?.('[data-tip-value]');

  document.addEventListener('pointerover', (e) => target(e) && show(target(e)));
  document.addEventListener('pointerout', (e) => target(e) && hide(target(e)));
  document.addEventListener('focusin', (e) => target(e) && show(target(e)));
  document.addEventListener('focusout', (e) => target(e) && hide(target(e)));
  document.addEventListener('scroll', () => anchor && hide(anchor), true);
}
