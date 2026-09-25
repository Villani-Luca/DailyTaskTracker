// Stat tile: sentence-case label over a single value.

import { esc, icons } from '../util.js';

export function kpiHTML(label, value, { alert = false } = {}) {
  return `<div class="kpi${alert ? ' is-alert' : ''}">
    <span class="kpi-label">${alert ? icons.alert : ''}${esc(label)}</span>
    <span class="kpi-value">${esc(value)}</span>
  </div>`;
}
