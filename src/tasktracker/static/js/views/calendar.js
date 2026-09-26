// Calendar: planned blocks, time spent and appointments in folder colors, plus
// tasks planned for a day. Drag to move/resize, drop open tasks to schedule them.

/* global FullCalendar */

import { api } from '../api.js';
import { openBlockDialog } from '../components/blockDialog.js';
import { openTaskDrawer } from '../components/taskDrawer.js';
import { timeBarsHTML } from '../components/timeBars.js';
import { folderName, notifyChange } from '../store.js';
import {
  addDays, addMinutes, dateISO, describeRecurrence, esc, fmtDay, fmtMinutes, icons, inkOn, relDay,
  setPageTitle, showError, toLocalISO, toast,
} from '../util.js';

const PREFS_KEY = 'tasktracker.calendar';
const DEFAULT_PREFS = { view: 'timeGridWeek', planned: true, tracked: true, dayTasks: true };
const VIEW_NOUN = { dayGridMonth: 'month', timeGridWeek: 'week', listWeek: 'week', timeGridDay: 'day' };
const TIME_FORMAT = { hour: '2-digit', minute: '2-digit', hour12: false };

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
    <div class="calendar-layout">
      <div class="calendar-main card"><div data-calendar></div></div>
      <aside class="calendar-side">
        <section class="card">
          <h3>Show</h3>
          <label class="toggle"><input type="checkbox" data-pref="planned"${prefs.planned ? ' checked' : ''}>
            <span class="legend-swatch planned"></span>Planned time</label>
          <label class="toggle"><input type="checkbox" data-pref="tracked"${prefs.tracked ? ' checked' : ''}>
            <span class="legend-swatch tracked"></span>Time spent</label>
          <label class="toggle"><input type="checkbox" data-pref="dayTasks"${prefs.dayTasks ? ' checked' : ''}>
            <span class="legend-swatch daytask"></span>Tasks planned for the day</label>
          <p class="hint">Colors come from each folder. Drag on the grid to add a block.</p>
        </section>
        <section class="card" data-summary></section>
        <section class="card">
          <h3>Open tasks</h3>
          <p class="hint">Drag a task onto the calendar to schedule it.</p>
          <input type="search" placeholder="Filter…" aria-label="Filter open tasks" data-task-filter>
          <div class="drag-list" data-drag-list></div>
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
    initialView: prefs.view,
    headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek' },
    buttonText: { today: 'Today', month: 'Month', week: 'Week', day: 'Day', list: 'List' },
    firstDay: 1,
    height: '100%',
    nowIndicator: true,
    scrollTime: '07:30:00',
    snapDuration: '00:15:00',
    allDayText: 'Tasks',
    dayMaxEvents: true,
    eventDisplay: 'block',
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
      <h3>Time this ${VIEW_NOUN[range.view.type] ?? 'period'}</h3>
      <div class="summary-totals">
        <div><span class="label">Spent</span><strong>${fmtMinutes(report.tracked_minutes)}</strong></div>
        <div><span class="label">Planned</span><strong>${fmtMinutes(report.planned_minutes)}</strong></div>
      </div>
      ${timeBarsHTML(report.folders)}
      <p class="hint"><a href="#/reports">Open reports</a> for any range of dates.</p>`;
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
  dragListEl.addEventListener('click', (e) => {
    const item = e.target.closest('.drag-task');
    if (item) openTaskDrawer(Number(item.dataset.taskId));
  });

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
      clearInterval(ticker);
      draggable.destroy();
      calendar.destroy();
    },
  };
}
