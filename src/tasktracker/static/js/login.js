// Login page: check the credentials, then open the app.

import { api } from './api.js';

// Use the theme picked in the app (see app.js); otherwise follow the OS.
try {
  const theme = localStorage.getItem('tasktracker.theme');
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
} catch {
  // Storage unavailable: follow the OS.
}

const form = document.getElementById('login-form');
const error = document.getElementById('login-error');
const submit = form.querySelector('button[type="submit"]');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  submit.disabled = true;
  error.hidden = true;
  try {
    await api.auth.login(form.elements.username.value, form.elements.password.value);
    location.replace('/');
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
    form.elements.password.value = '';
    form.elements.password.focus();
    submit.disabled = false;
  }
});
