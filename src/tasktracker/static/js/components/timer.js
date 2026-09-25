// The running-timer widget in the top bar.

import { api } from '../api.js';
import { notifyChange } from '../store.js';
import { esc, fmtElapsed, icons, showError } from '../util.js';
import { openTaskDrawer } from './taskDrawer.js';

let running = null;
let ticker = null;

function render() {
  const el = document.getElementById('timer-widget');
  clearInterval(ticker);
  if (!running) {
    el.innerHTML = `<span class="timer-idle">${icons.clock}No timer running</span>`;
    document.title = 'Daily Task Tracker';
    return;
  }
  el.innerHTML = `
    <div class="timer-running" style="--c:${running.color}">
      <span class="pulse" aria-hidden="true"></span>
      <button class="timer-task" data-open title="Open task">${esc(running.display_title)}</button>
      <span class="timer-elapsed" aria-live="off"></span>
      <button class="btn btn-sm" data-stop>${icons.stop}Stop</button>
    </div>`;
  const elapsedEl = el.querySelector('.timer-elapsed');
  const started = new Date(running.starts_at);
  const tick = () => {
    const text = fmtElapsed(Date.now() - started);
    elapsedEl.textContent = text;
    document.title = `${text} · ${running.display_title}`;
  };
  tick();
  ticker = setInterval(tick, 1000);
  el.querySelector('[data-open]').addEventListener('click', () => openTaskDrawer(running.task_id));
  el.querySelector('[data-stop]').addEventListener('click', async () => {
    try {
      await api.timer.stop();
      notifyChange();
    } catch (err) {
      showError(err);
    }
  });
}

export async function refreshTimer() {
  running = await api.timer.get();
  render();
}
