// Time spent vs. planned per folder: two thin bars per folder on a shared scale.

import { esc, fmtMinutes } from '../util.js';

export function timeBarsHTML(folders, empty = 'Nothing on the calendar in this range yet.') {
  if (!folders.length) return `<p class="empty">${esc(empty)}</p>`;
  const max = Math.max(1, ...folders.flatMap((f) => [f.tracked_minutes, f.planned_minutes]));
  const width = (m) => `${(m / max) * 100}%`;
  return `<ul class="time-bars">${folders
    .map(
      (f) => `<li style="--c:${f.color}">
        <div class="tb-head">
          <i class="dot"></i><span class="tb-name">${esc(f.name)}</span>
          <span class="tb-values">${fmtMinutes(f.tracked_minutes)}<span class="muted"> / ${fmtMinutes(f.planned_minutes)}</span></span>
        </div>
        <div class="tb-track"><span class="tb-bar tracked" style="width:${width(f.tracked_minutes)}" tabindex="0"
          data-tip-value="${fmtMinutes(f.tracked_minutes)} spent" data-tip-label="${esc(f.name)}"></span></div>
        <div class="tb-track"><span class="tb-bar planned" style="width:${width(f.planned_minutes)}" tabindex="0"
          data-tip-value="${fmtMinutes(f.planned_minutes)} planned" data-tip-label="${esc(f.name)}"></span></div>
      </li>`,
    )
    .join('')}</ul>
    <p class="hint"><span class="legend-swatch tracked"></span>spent <span class="legend-swatch planned"></span>planned</p>`;
}
