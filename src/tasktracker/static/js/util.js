// Formatting, dates and small DOM helpers shared by every view.

export const STATUSES = [
  { value: 'todo', label: 'To do' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'blocked', label: 'Blocked' },
  { value: 'done', label: 'Done' },
];
export const STATUS_LABEL = Object.fromEntries(STATUSES.map((s) => [s.value, s.label]));

// Stacked status bars lead with progress: Done | In progress | Blocked | To do.
export const STATUS_BAR_ORDER = ['done', 'in_progress', 'blocked', 'todo'];

export const PRIORITIES = [
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
];

// Folder color presets (a CVD-checked categorical order); any hex color is allowed.
export const FOLDER_COLORS = [
  '#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948',
];

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

// --- Dates (the API speaks naive local time: "2026-09-25T09:30:00") ---------------

const pad = (n) => String(n).padStart(2, '0');

export const dateISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const toLocalISO = (d) =>
  `${dateISO(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
export const toInputDateTime = (d) => `${dateISO(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const todayISO = () => dateISO(new Date());

/** "2026-09-25" -> local midnight (new Date("2026-09-25") would be UTC midnight). */
export function parseDay(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(date, days) {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}

export function addMinutes(date, minutes) {
  return new Date(date.getTime() + minutes * 60_000);
}

/** Same day `months` later, or that month's last day when it is shorter (31 Jan -> 28 Feb). */
export function addMonths(date, months) {
  const d = new Date(date);
  const day = d.getDate();
  d.setDate(1);
  d.setMonth(d.getMonth() + months);
  d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
  return d;
}

/** Monday of the week `date` falls in, at midnight (the calendar's weeks start on Monday). */
export function startOfWeek(date) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return addDays(d, -((d.getDay() + 6) % 7));
}

/** Short weekday names in the browser's language, Monday first (the API's 0-6). */
export const WEEKDAYS = Array.from({ length: 7 }, (_, i) =>
  new Date(2024, 0, 1 + i).toLocaleDateString(undefined, { weekday: 'short' }),
);

/** "Every 2 weeks on Mon, Wed until 21 Oct 2026". `start` names the day of the month. */
export function describeRecurrence(r, start = null) {
  const [one, many] = { daily: ['day', 'days'], weekly: ['week', 'weeks'], monthly: ['month', 'months'] }[r.frequency];
  let text = r.interval === 1 ? `Every ${one}` : `Every ${r.interval} ${many}`;
  if (r.frequency === 'weekly') text += ` on ${r.weekdays.map((d) => WEEKDAYS[d]).join(', ')}`;
  if (r.frequency === 'monthly' && start) text += ` on day ${new Date(start).getDate()}`;
  return `${text} until ${fmtDay(r.until, { day: 'numeric', month: 'short', year: 'numeric' })}`;
}

export function fmtDay(iso, options = { weekday: 'short', day: 'numeric', month: 'short' }) {
  return parseDay(iso).toLocaleDateString(undefined, options);
}

/** "Today", "Tomorrow", "Yesterday" or "Fri 25 Sep". */
export function relDay(iso) {
  const diff = Math.round((parseDay(iso) - parseDay(todayISO())) / 86_400_000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff === -1) return 'Yesterday';
  return fmtDay(iso);
}

export function fmtTime(isoDateTime) {
  return new Date(isoDateTime).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export function fmtDateTime(isoDateTime) {
  const d = new Date(isoDateTime);
  return `${fmtDay(dateISO(d))}, ${fmtTime(isoDateTime)}`;
}

export function fmtMinutes(minutes) {
  if (!minutes) return '0m';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function fmtElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${pad(m)}:${pad(s)}`;
}

/** Parse "90", "45m", "1h", "1h 30m", "1.5h" into minutes. '' -> null, junk -> NaN. */
export function parseDuration(text) {
  const s = String(text ?? '').trim().toLowerCase();
  if (!s) return null;
  if (/^\d+$/.test(s)) return Number(s);
  const match = s.match(/^(?:(\d+(?:[.,]\d+)?)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?$/);
  if (!match || (!match[1] && !match[2])) return NaN;
  const hours = match[1] ? Number(match[1].replace(',', '.')) : 0;
  return Math.round(hours * 60 + (match[2] ? Number(match[2]) : 0));
}

// --- Color -------------------------------------------------------------------------

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Readable text color (near-black or white) on a solid `hex` fill: the higher contrast wins. */
export function inkOn(hex) {
  const l = luminance(hex);
  const onWhite = 1.05 / (l + 0.05);
  const onDark = (l + 0.05) / (luminance('#0b0b0b') + 0.05);
  return onWhite >= onDark ? '#ffffff' : '#0b0b0b';
}

// --- DOM ---------------------------------------------------------------------------

export function $(selector, root = document) {
  return root.querySelector(selector);
}

export function h(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

let toastTimer;
export function toast(message, kind = 'info') {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = 'toast'), kind === 'error' ? 5000 : 2200);
}

export function showError(error) {
  console.error(error);
  toast(error?.message || 'Something went wrong', 'error');
}

const svg = (body, { fill = false } = {}) =>
  `<svg class="icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" ${
    fill ? 'fill="currentColor"' : 'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
  }>${body}</svg>`;

export const icons = {
  play: svg('<path d="M5 3.2v9.6c0 .4.4.6.7.4l7.4-4.8a.5.5 0 0 0 0-.8L5.7 2.8c-.3-.2-.7 0-.7.4z"/>', { fill: true }),
  stop: svg('<rect x="3.5" y="3.5" width="9" height="9" rx="1.5"/>', { fill: true }),
  check: svg('<path d="M3.5 8.5l3 3 6-7"/>'),
  calendar: svg('<rect x="2.5" y="3.5" width="11" height="10" rx="1.5"/><path d="M2.5 6.5h11M5.5 2v3M10.5 2v3"/>'),
  clock: svg('<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.2l2 1.3"/>'),
  comment: svg('<path d="M3 3.5h10a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H7l-3 2.5v-2.5H3a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1z"/>'),
  trash: svg('<path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5"/>'),
  plus: svg('<path d="M8 3v10M3 8h10"/>'),
  edit: svg('<path d="M10.5 3l2.5 2.5L6 12.5H3.5V10z"/>'),
  close: svg('<path d="M4 4l8 8M12 4l-8 8"/>'),
  alert: svg('<path d="M8 2.5l6 10.5H2z"/><path d="M8 6.5v3M8 11.3v.2"/>'),
  flag: svg('<path d="M4 14V2.5M4 3h7.5l-1.5 3 1.5 3H4"/>'),
  grip: svg('<circle cx="6" cy="4" r="1"/><circle cx="10" cy="4" r="1"/><circle cx="6" cy="8" r="1"/><circle cx="10" cy="8" r="1"/><circle cx="6" cy="12" r="1"/><circle cx="10" cy="12" r="1"/>', { fill: true }),
  folder: svg('<path d="M2 4.5a1 1 0 0 1 1-1h3.2l1.5 1.5H13a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z"/>'),
  sun: svg('<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1"/>'),
  repeat: svg('<path d="M3 7V6a2 2 0 0 1 2-2h7.5M10.5 2l2 2-2 2M13 9v1a2 2 0 0 1-2 2H3.5M5.5 14l-2-2 2-2"/>'),
};

export function setPageTitle(text, color = null) {
  const el = document.getElementById('page-title');
  el.innerHTML = `${color ? `<i class="dot lg" style="--c:${color}"></i>` : ''}${esc(text)}`;
}
