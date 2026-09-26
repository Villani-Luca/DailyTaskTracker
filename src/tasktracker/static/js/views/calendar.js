// Calendar: planned blocks, time spent and appointments in folder colors, plus
// tasks planned for a day. Drag to move/resize, drop open tasks to schedule them.

/* global FullCalendar */

import { api } from '../api.js';
import { openBlockDialog } from '../components/blockDialog.js';
import { acceptDroppedFiles, openImportDialog } from '../components/importDialog.js';
import { bindPaneTabs, paneTabsHTML } from '../components/panes.js';
import { openTaskDrawer } from '../components/taskDrawer.js';
import { timeBarsHTML } from '../components/timeBars.js';
import { folderName, notifyChange } from '../store.js';
import {
  addDays, addMinutes, dateISO, describeRecurrence, esc, fmtDay, fmtMinutes, icons, inkOn, relDay,
  setPageTitle, showError, toLocalISO, toast,
} from '../util.js';

const PREFS_KEY = 'tasktracker.calendar';
const DEFAULT_PREFS = { view: 'timeGridWeek', planned: true, tracked: true, dayTasks: true };
const SUMMARY_TITLE = {
  dayGridMonth: 'Time this month',
  timeGridWeek: 'Time this week',
  listWeek: 'Time this week',
  timeGrid3Day: 'Time in these 3 days',
  timeGridDay: 'Time this day',
};
const TIME_FORMAT = { hour: '2-digit', minute: '2-digit', hour12: false };

// Seven columns don't fit a phone: there, the week view shows three days instead.
const NARROW = window.matchMedia('(max-width: 760px)');

function fitView(view) {
  if (NARROW.matches) return view === 'timeGridWeek' ? 'timeGrid3Day' : view;
  return view === 'timeGrid3Day' ? 'timeGridWeek' : view;
}

function headerToolbar() {
  const views = `dayGridMonth,${fitView('timeGridWeek')},timeGridDay,listWeek`;
  // On a phone the chunks stack (see app.css): arrows around the title, then the rest.
  return NARROW.matches
    ? { left: 'prev title next', center: '', right: `today ${views}` }
    : { left: 'prev,next today', center: 'title', right: views };
}

function loadPrefs() {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

function savePrefs(prefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // Storage unavailable (private mode): preferences just don't persist.
  }
}

function blockEvent(block) {
  // A running timer grows until "now"; keep it visible even in its first minutes.
  const end = block.ends_at ?? toLocalISO(new Date(Math.max(Date.now(), new Date(block.starts_at).getTime() + 15 * 60_000)));
  return {
    id: `block-${block.id}`,
    title: block.display_title,
    start: block.starts_at,
    end,
    borderColor: block.color,
    editable: !block.is_running,
    classNames: ['ev', `ev-${block.kind}`, ...(block.is_running ? ['ev-running'] : [])],
    extendedProps: { type: 'block', block },
  };
}

function taskEvent(task) {
  return {
    id: `task-${task.id}`,
    title: task.title,
    start: task.planned_date,
    allDay: true,
    borderColor: task.color,
    durationEditable: false,
    classNames: ['ev', 'ev-daytask', ...(task.status === 'done' ? ['is-done'] : [])],
    extendedProps: { type: 'task', task },
  };
}

export async function mount(root) {
  setPageTitle('Calendar');
  const prefs = loadPrefs();
  root.innerHTML = `
    ${paneTabsHTML([['calendar', 'Calendar'], ['tasks', 'Open tasks'], ['time', 'Time'], ['options', 'Options']])}
    <div class="calendar-layout panes">
      <div class="calendar-main card pane" data-pane="calendar"><div data-calendar></div></div>
      <aside class="calendar-side">
        <section class="card slot pane calendar-options" data-pane="options">
          <div class="slot-body">
            <h3>Show</h3>
            <label class="toggle"><input type="checkbox" data-pref="planned"${prefs.planned ? ' checked' : ''}>
              <span class="legend-swatch planned"></span>Planned time</label>
            <label class="toggle"><input type="checkbox" data-pref="tracked"${prefs.tracked ? ' checked' : ''}>
              <span class="legend-swatch tracked"></span>Time spent</label>
            <label class="toggle"><input type="checkbox" data-pref="dayTasks"${prefs.dayTasks ? ' checked' : ''}>
              <span class="legend-swatch daytask"></span>Tasks planned for the day</label>
            <p class="hint">Colors come from each folder.
              <span class="wide-only">Drag on the grid to add a block.</span>
              <span class="phone-only">Press and hold on the grid to add a block.</span></p>
            <h3 class="options-divider">Appointments</h3>
            <button type="button" class="btn btn-sm" data-import>${icons.upload}Import invite, email or calendar</button>
            <p class="hint">From an .ics file, a saved email (.eml), pasted text or a calendar link.
              Or drop the file on the calendar.</p>
          </div>
        </section>
        <section class="card slot pane calendar-summary" data-pane="time" data-summary></section>
        <section class="card slot pane calendar-tasks" data-pane="tasks">
          <h3>Open tasks</h3>
          <p class="hint wide-only">Drag a task onto the calendar to schedule it.</p>
          <p class="hint phone-only">Tap a task to open it and plan it.</p>
          <input type="search" placeholder="Filter…" aria-label="Filter open tasks" data-task-filter>
          <div class="drag-list slot-body" data-drag-list></div>
        </section>
      </aside>
    </div>`;

  const summaryEl = root.querySelector('[data-summary]');
  const dragListEl = root.querySelector('[data-drag-list]');
  const filterEl = root.querySelector('[data-task-filter]');
  let openTasks = [];
  let range = null;
  let hasRunningTimer = false;

  async function fetchEvents(info, success, failure) {
    try {
      const [blocks, dayTasks] = await Promise.all([
        api.blocks.list(toLocalISO(info.start), toLocalISO(info.end)),
        prefs.dayTasks
          ? api.tasks.list({ planned_from: dateISO(info.start), planned_to: dateISO(addDays(info.end, -1)) })
          : [],
      ]);
      hasRunningTimer = blocks.some((b) => b.is_running);
      // A task already placed on the grid that day doesn't need its all-day chip too.
      const placed = new Set(
        blocks.filter((b) => b.task_id && b.kind === 'planned').map((b) => `${b.task_id}@${dateISO(new Date(b.starts_at))}`),
      );
      success([
        ...blocks.filter((b) => prefs[b.kind]).map(blockEvent),
        ...dayTasks.filter((t) => !placed.has(`${t.id}@${t.planned_date}`)).map(taskEvent),
      ]);
    } catch (err) {
      failure(err);
      showError(err);
    }
  }

  function decorate(info) {
    const { type, block, task } = info.event.extendedProps;
    const color = block?.color ?? task?.color ?? info.event.borderColor;
    if (!color) return;
    info.el.style.setProperty('--ev', color);
    info.el.style.setProperty('--ev-ink', inkOn(color));
    if (type === 'block') {
      const kind = block.is_running ? 'Running timer' : block.kind === 'tracked' ? 'Time spent' : 'Planned';
      const repeats = block.recurrence && block.kind === 'planned' ? `\n${describeRecurrence(block.recurrence, block.starts_at)}` : '';
      info.el.title = `${block.display_title}\n${kind} · ${folderName(block.effective_folder_id)} · ${fmtMinutes(block.duration_minutes)}${repeats}`;
    } else if (type === 'task') {
      info.el.title = `${task.title}\nPlanned for the day · ${folderName(task.folder_id)}`;
    }
  }

  async function onMove(info) {
    const { type, block, task } = info.event.extendedProps;
    const ev = info.event;
    try {
      if (type === 'block') {
        if (ev.allDay) {
          info.revert();
          toast('Calendar blocks need a time: drop them on the time grid', 'error');
          return;
        }
        await api.blocks.update(block.id, {
          starts_at: toLocalISO(ev.start),
          ends_at: toLocalISO(ev.end ?? addMinutes(ev.start, block.duration_minutes || 60)),
        });
      } else if (ev.allDay) {
        await api.tasks.update(task.id, { planned_date: dateISO(ev.start) });
      } else {
        // A day task dropped on the time grid gets a planned block on that day.
        await api.tasks.update(task.id, { planned_date: dateISO(ev.start) });
        await api.blocks.create({
          task_id: task.id,
          kind: 'planned',
          starts_at: toLocalISO(ev.start),
          ends_at: toLocalISO(addMinutes(ev.start, task.estimate_minutes || 60)),
        });
      }
      notifyChange();
    } catch (err) {
      info.revert();
      showError(err);
    }
  }

  async function onExternalDrop(info) {
    const task = openTasks.find((t) => t.id === Number(info.draggedEl.dataset.taskId));
    if (!task) return;
    try {
      if (info.allDay) {
        await api.tasks.update(task.id, { planned_date: dateISO(info.date) });
        toast(`Planned for ${fmtDay(dateISO(info.date))}`);
      } else {
        await api.blocks.create({
          task_id: task.id,
          kind: 'planned',
          starts_at: toLocalISO(info.date),
          ends_at: toLocalISO(addMinutes(info.date, task.estimate_minutes || 60)),
        });
        toast('Scheduled');
      }
      notifyChange();
    } catch (err) {
      showError(err);
    }
  }

  const calendar = new FullCalendar.Calendar(root.querySelector('[data-calendar]'), {
    initialView: fitView(prefs.view),
    headerToolbar: headerToolbar(),
    buttonText: { today: 'Today', month: 'Month', week: 'Week', day: 'Day', list: 'List' },
    views: { timeGrid3Day: { type: 'timeGrid', duration: { days: 3 }, buttonText: '3 days' } },
    firstDay: 1,
    height: '100%',
    nowIndicator: true,
    scrollTime: '07:30:00',
    snapDuration: '00:15:00',
    allDayText: 'Tasks',
    dayMaxEvents: true,
    eventDisplay: 'block',
    // Short blocks stay readable: at least one line tall, one line of title when under
    // ~25 minutes (see .fc-timegrid-event-short in app.css), and side by side, not stacked.
    eventMinHeight: 18,
    eventShortHeight: 30,
    slotEventOverlap: false,
    eventTimeFormat: TIME_FORMAT,
    slotLabelFormat: TIME_FORMAT,
    editable: true,
    selectable: true,
    selectMirror: true,
    droppable: true,
    events: fetchEvents,
    eventDidMount: decorate,
    eventDrop: onMove,
    eventResize: onMove,
    drop: onExternalDrop,
    select(info) {
      calendar.unselect();
      let { start, end } = info;
      if (info.allDay) {
        start = new Date(info.start);
        start.setHours(9, 0, 0, 0);
        end = addMinutes(start, 60);
      }
      openBlockDialog({ start, end });
    },
    eventClick(info) {
      info.jsEvent.preventDefault();
      const { type, block, task } = info.event.extendedProps;
      if (type === 'task') openTaskDrawer(task.id);
      else openBlockDialog({ block });
    },
    datesSet(info) {
      range = info;
      prefs.view = info.view.type;
      savePrefs(prefs);
      loadSummary().catch(showError);
    },
  });

  const draggable = new FullCalendar.Draggable(dragListEl, {
    itemSelector: '.drag-task',
    eventData(el) {
      const task = openTasks.find((t) => t.id === Number(el.dataset.taskId));
      return {
        title: task?.title ?? '',
        duration: { minutes: task?.estimate_minutes || 60 },
        create: false,
        borderColor: task?.color,
        classNames: ['ev', 'ev-planned'],
      };
    },
  });

  async function loadSummary() {
    if (!range) return;
    const report = await api.timeReport(toLocalISO(range.start), toLocalISO(range.end));
    summaryEl.innerHTML = `
      <h3>${SUMMARY_TITLE[range.view.type] ?? 'Time in this period'}</h3>
      <div class="slot-body">
        <div class="summary-totals">
          <div><span class="label">Spent</span><strong>${fmtMinutes(report.tracked_minutes)}</strong></div>
          <div><span class="label">Planned</span><strong>${fmtMinutes(report.planned_minutes)}</strong></div>
        </div>
        ${timeBarsHTML(report.folders)}
        <p class="hint"><a href="#/reports">Open reports</a> for any range of dates.</p>
      </div>`;
  }

  function renderDragList() {
    const q = filterEl.value.trim().toLowerCase();
    const visible = openTasks.filter((t) => !q || t.title.toLowerCase().includes(q));
    dragListEl.innerHTML = visible.length
      ? visible
          .map(
            (t) => `<div class="drag-task" data-task-id="${t.id}" style="--c:${t.color}" title="Drag onto the calendar, or click to open">
              <span class="grip">${icons.grip}</span>
              <i class="dot"></i>
              <span class="drag-title">${esc(t.title)}</span>
              <span class="drag-meta">${t.planned_date ? relDay(t.planned_date) : 'Unplanned'} · ${fmtMinutes(t.estimate_minutes || 60)}</span>
            </div>`,
          )
          .join('')
      : `<p class="empty">${openTasks.length ? 'No match.' : 'No open tasks.'}</p>`;
  }

  async function loadOpenTasks() {
    openTasks = await api.tasks.list({ status: ['todo', 'in_progress', 'blocked'] });
    renderDragList();
  }

  root.querySelectorAll('[data-pref]').forEach((input) =>
    input.addEventListener('change', () => {
      prefs[input.dataset.pref] = input.checked;
      savePrefs(prefs);
      calendar.refetchEvents();
    }),
  );
  filterEl.addEventListener('input', renderDragList);
  root.querySelector('[data-import]').addEventListener('click', () => openImportDialog());
  acceptDroppedFiles(root.querySelector('.calendar-layout'));
  dragListEl.addEventListener('click', (e) => {
    const item = e.target.closest('.drag-task');
    if (item) openTaskDrawer(Number(item.dataset.taskId));
  });

  // Rotating a tablet or resizing a window can cross the phone breakpoint.
  const onNarrowChange = () => {
    calendar.setOption('headerToolbar', headerToolbar());
    const view = fitView(calendar.view.type);
    if (view !== calendar.view.type) calendar.changeView(view);
  };
  NARROW.addEventListener('change', onNarrowChange);

  // A calendar laid out while its tab was hidden has no size yet.
  bindPaneTabs(root, 'calendar', { onShow: (pane) => pane === 'calendar' && calendar.updateSize() });

  calendar.render();
  await loadOpenTasks();

  // Let a running timer's block grow on screen.
  const ticker = setInterval(() => hasRunningTimer && calendar.refetchEvents(), 60_000);

  return {
    async refresh() {
      calendar.refetchEvents();
      await Promise.all([loadSummary(), loadOpenTasks()]);
    },
    destroy() {
      NARROW.removeEventListener('change', onNarrowChange);
      clearInterval(ticker);
      draggable.destroy();
      calendar.destroy();
    },
  };
}
