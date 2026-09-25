// Projects: one card per folder with its status breakdown, completion and time.

import { api } from '../api.js';
import { openFolderDialog } from '../components/folderDialog.js';
import { statusBarHTML } from '../components/statusBar.js';
import { esc, fmtMinutes, icons, setPageTitle } from '../util.js';

function cardHTML(s) {
  const href = `#/folder/${s.folder_id ?? 'inbox'}`;
  const estimate = s.estimate_minutes ? ` of ${fmtMinutes(s.estimate_minutes)} estimated` : '';
  return `<section class="card project-card" data-href="${href}" style="--c:${s.color}">
    <header class="project-header">
      <i class="dot lg"></i>
      <h3><a href="${href}">${esc(s.name)}</a></h3>
      <span class="muted small">${s.total_tasks} ${s.total_tasks === 1 ? 'task' : 'tasks'}</span>
    </header>
    <div class="completion">
      <span class="completion-value">${Math.round(s.completion_percent)}%</span>
      <span class="muted">done</span>
    </div>
    ${statusBarHTML(s.statuses)}
    <footer class="project-foot">
      <span>${icons.clock}${fmtMinutes(s.tracked_minutes)} spent${estimate}</span>
      ${s.overdue_tasks ? `<span class="meta-late">${icons.alert}${s.overdue_tasks} overdue</span>` : ''}
    </footer>
  </section>`;
}

export async function mount(root) {
  setPageTitle('Projects');
  const load = async () => {
    const stats = await api.folders.stats();
    root.innerHTML = `
      <div class="page-intro">
        <p class="muted">Progress per folder. Open a folder to see and manage its tasks.</p>
        <button class="btn btn-primary" data-new-folder>${icons.plus}New folder</button>
      </div>
      ${
        stats.length
          ? `<div class="projects-grid">${stats.map(cardHTML).join('')}</div>`
          : '<div class="card empty-state"><p>No folders yet. Create one to group your tasks, like Work, Home or a side project.</p></div>'
      }`;
  };

  root.addEventListener('click', (e) => {
    if (e.target.closest('[data-new-folder]')) {
      openFolderDialog().then((folder) => folder && (location.hash = `#/folder/${folder.id}`));
      return;
    }
    const card = e.target.closest('[data-href]');
    if (card && !e.target.closest('a, button, .seg')) location.hash = card.dataset.href;
  });

  await load();
  return { refresh: load };
}
