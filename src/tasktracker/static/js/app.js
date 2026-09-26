// App shell: hash router, sidebar, theme, and refresh-on-change.

import { api } from './api.js';
import { openFolderDialog } from './components/folderDialog.js';
import { installTooltips } from './components/statusBar.js';
import { refreshTaskDrawer } from './components/taskDrawer.js';
import { refreshTimer } from './components/timer.js';
import { loadFolders, onChange, store } from './store.js';
import { esc, showError } from './util.js';
import * as calendar from './views/calendar.js';
import * as folder from './views/folder.js';
import * as overview from './views/overview.js';
import * as projects from './views/projects.js';

const routes = { overview, calendar, projects, folder };
const INBOX_COLOR = '#8a8f98';

let current = null;
let navigation = 0;

function parseHash() {
  const [name, param] = location.hash.replace(/^#\/?/, '').split('/');
  return { name: routes[name] ? name : 'overview', param };
}

function highlightNav() {
  const { name, param } = parseHash();
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('is-active', a.dataset.nav === name));
  document.querySelectorAll('[data-folder-key]').forEach((a) =>
    a.classList.toggle('is-active', name === 'folder' && a.dataset.folderKey === param),
  );
}

async function renderRoute() {
  const token = ++navigation;
  const { name, param } = parseHash();
  current?.destroy?.();
  current = null;
  const root = document.createElement('div');
  root.className = `view view-${name}`;
  document.getElementById('view').replaceChildren(root);
  highlightNav();
  try {
    const mounted = await routes[name].mount(root, param);
    if (token !== navigation) {
      mounted?.destroy?.();
      return;
    }
    current = mounted;
  } catch (err) {
    root.innerHTML = `<div class="card empty-state"><p>Could not load this page: ${esc(err.message)}</p></div>`;
    showError(err);
  }
}

async function renderSidebar() {
  const stats = await api.folders.stats();
  const open = new Map(stats.map((s) => [s.folder_id, s.open_tasks]));
  const items = [
    { key: 'inbox', name: 'Inbox', color: INBOX_COLOR, count: open.get(null) ?? 0 },
    ...store.folders.map((f) => ({ key: String(f.id), name: f.name, color: f.color, count: open.get(f.id) ?? 0 })),
  ];
  document.getElementById('folder-list').innerHTML = items
    .map(
      (i) => `<li><a href="#/folder/${i.key}" data-folder-key="${i.key}">
        <i class="dot" style="--c:${i.color}"></i><span class="name">${esc(i.name)}</span>
        ${i.count ? `<span class="count" title="${i.count} open">${i.count}</span>` : ''}
      </a></li>`,
    )
    .join('');
  highlightNav();
}

// Theme: follow the OS, or force light/dark. The choice is a per-browser convenience.
const THEMES = ['auto', 'light', 'dark'];
function applyTheme(theme) {
  if (theme === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  document.getElementById('theme-label').textContent = `Theme: ${theme}`;
}
function initTheme() {
  let theme = 'auto';
  try {
    theme = localStorage.getItem('tasktracker.theme') || 'auto';
  } catch {
    // Storage unavailable: stay on auto.
  }
  applyTheme(theme);
  document.getElementById('theme-toggle').addEventListener('click', () => {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    applyTheme(theme);
    try {
      localStorage.setItem('tasktracker.theme', theme);
    } catch {
      // Not persisted; fine.
    }
  });
}

async function refreshAll() {
  try {
    await loadFolders();
    await Promise.all([renderSidebar(), refreshTimer(), current?.refresh?.(), refreshTaskDrawer()]);
  } catch (err) {
    showError(err);
  }
}

async function initAccount() {
  const me = await api.auth.me(); // not logged in: api.js sends us to /login
  const name = document.getElementById('account-name');
  name.textContent = me.username;
  name.title = `Logged in as ${me.username}`;
  document.getElementById('logout-btn').addEventListener('click', async () => {
    try {
      await api.auth.logout();
      location.replace('/login');
    } catch (err) {
      showError(err);
    }
  });
}

async function init() {
  installTooltips();
  initTheme();
  await initAccount();
  document.getElementById('new-folder-btn').addEventListener('click', async () => {
    const created = await openFolderDialog();
    if (created) location.hash = `#/folder/${created.id}`;
  });
  onChange(refreshAll);
  window.addEventListener('hashchange', renderRoute);

  await loadFolders();
  await Promise.all([renderSidebar(), refreshTimer()]);
  await renderRoute();
}

init().catch(showError);
