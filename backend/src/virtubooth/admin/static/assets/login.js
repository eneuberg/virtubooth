import { api } from '/static/core/vb.js';

// only same-site admin pages, never an open redirect
const NEXT_RE = /^\/admin\/[a-z0-9-]*(\?id=\d{1,9})?$/;

export function safeNext(raw) {
  if (!raw || !NEXT_RE.test(raw) || raw === '/admin/' || raw === '/admin/login') return '/admin/live';
  return raw;
}

const next = safeNext(new URLSearchParams(location.search).get('next'));
const form = document.getElementById('login-form');
const input = document.getElementById('password');
const errorEl = document.getElementById('login-error');
const submit = document.getElementById('login-submit');

async function alreadyLoggedIn() {
  try {
    const s = await api('/api/admin/session');
    if (s.authenticated) location.replace(next);
  } catch (_) { /* show the form */ }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorEl.textContent = '';
  if (!input.value) {
    errorEl.textContent = 'Bitte das Passwort eingeben.';
    input.focus();
    return;
  }
  submit.disabled = true;
  submit.textContent = 'Prüfe…';
  try {
    await api('/api/admin/login', { method: 'POST', json: { password: input.value } });
    submit.textContent = 'Willkommen!';
    location.replace(next);
  } catch (err) {
    errorEl.textContent = err.message || 'Login fehlgeschlagen.';
    submit.disabled = false;
    submit.textContent = 'Anmelden';
    input.select();
  }
});

alreadyLoggedIn();
