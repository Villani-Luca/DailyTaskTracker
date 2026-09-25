// Shared client state and a tiny change bus: any mutation calls notifyChange(),
// and the app refreshes the sidebar, the timer and the current view.

import { api } from './api.js';

export const store = {
  folders: [],
};

export async function loadFolders() {
  store.folders = await api.folders.list();
  return store.folders;
}

export function folderById(id) {
  return store.folders.find((f) => f.id === id) ?? null;
}

export function folderName(id) {
  return folderById(id)?.name ?? 'Inbox';
}

const listeners = new Set();
let scheduled = false;

export function onChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notifyChange() {
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(() => {
    scheduled = false;
    listeners.forEach((listener) => listener());
  });
}
