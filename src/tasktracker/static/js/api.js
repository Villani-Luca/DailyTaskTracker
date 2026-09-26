// Thin client for the JSON API (see /docs for the OpenAPI schema).

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function errorMessage(data, fallback) {
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => String(d.msg ?? d).replace(/^Value error, /, '')).join('; ');
  }
  return fallback;
}

async function request(method, path, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, init);
  if (res.status === 401 && path !== '/auth/login') {
    // Logged out, or the session expired: go and log in. The promise never settles, so
    // the page doesn't flash an error while it navigates away.
    location.assign('/login');
    return new Promise(() => {});
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(data, res.statusText), res.status);
  return data;
}

function query(params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    for (const v of Array.isArray(value) ? value : [value]) qs.append(key, v);
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
}

export const api = {
  auth: {
    me: () => request('GET', '/auth/me'),
    login: (username, password) => request('POST', '/auth/login', { username, password }),
    logout: () => request('POST', '/auth/logout'),
  },
  folders: {
    list: () => request('GET', '/folders'),
    stats: () => request('GET', '/folders/stats'),
    get: (id) => request('GET', `/folders/${id}`),
    create: (data) => request('POST', '/folders', data),
    update: (id, data) => request('PATCH', `/folders/${id}`, data),
    remove: (id) => request('DELETE', `/folders/${id}`),
  },
  tasks: {
    list: (params) => request('GET', `/tasks${query(params)}`),
    get: (id) => request('GET', `/tasks/${id}`),
    create: (data) => request('POST', '/tasks', data),
    update: (id, data) => request('PATCH', `/tasks/${id}`, data),
    remove: (id) => request('DELETE', `/tasks/${id}`),
    blocks: (id) => request('GET', `/tasks/${id}/blocks`),
  },
  comments: {
    list: (taskId) => request('GET', `/tasks/${taskId}/comments`),
    add: (taskId, body) => request('POST', `/tasks/${taskId}/comments`, { body }),
    remove: (id) => request('DELETE', `/comments/${id}`),
  },
  blocks: {
    list: (startsAt, endsAt) => request('GET', `/blocks${query({ starts_at: startsAt, ends_at: endsAt })}`),
    create: (data) => request('POST', '/blocks', data),
    // scope: for an event of a repeating series, 'this' (default), 'following' or 'all'
    update: (id, data, scope) => request('PATCH', `/blocks/${id}${query({ scope })}`, data),
    remove: (id, scope) => request('DELETE', `/blocks/${id}${query({ scope })}`),
  },
  timer: {
    get: () => request('GET', '/timer'),
    start: (taskId) => request('POST', '/timer/start', { task_id: taskId }),
    stop: () => request('POST', '/timer/stop'),
  },
  overview: (days = 6) => request('GET', `/overview${query({ days })}`),
  timeReport: (startsAt, endsAt) =>
    request('GET', `/reports/time${query({ starts_at: startsAt, ends_at: endsAt })}`),
};
