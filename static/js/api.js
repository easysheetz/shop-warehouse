// Komunikacja z serwerem. Aplikacja działa tylko z internetem – przy braku połączenia
// pokazujemy czerwony pasek, a operacja kończy się wyraźnym błędem.
import { state } from './state.js';

export class ApiError extends Error {
  constructor(message, status = 0, code = '') { super(message); this.status = status; this.code = code; }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export function setOnline(value) {
  state.online = value;
  const bar = document.getElementById('netbar');
  if (bar) bar.classList.toggle('hidden', value);
  document.body.classList.toggle('is-offline', !value);
}

export async function checkConnection() {
  try {
    const r = await fetch('/health', { cache: 'no-store' });
    setOnline(r.ok);
  } catch { setOnline(false); }
  return state.online;
}

window.addEventListener('offline', () => setOnline(false));
window.addEventListener('online', () => { checkConnection(); });

export async function api(path, opts = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout || 20000);
  const headers = { ...(opts.headers || {}) };
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  let body = opts.body;
  if (body !== undefined && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
  let res;
  try {
    res = await fetch(path, { method: opts.method || (body !== undefined ? 'POST' : 'GET'), headers, body, signal: ctrl.signal });
  } catch {
    setOnline(false);
    throw new ApiError('Brak połączenia z internetem – nic nie zostało zapisane', 0, 'offline');
  } finally { clearTimeout(timer); }
  setOnline(true);
  let data = null;
  try { data = await res.json(); } catch { /* pusta odpowiedź */ }
  if (res.status === 401 && !path.startsWith('/api/login')) {
    onUnauthorized();
    throw new ApiError((data && data.detail) || 'Zaloguj się ponownie', 401);
  }
  if (!res.ok) {
    let d = data && data.detail;
    if (Array.isArray(d)) d = d.map((x) => x.msg).join(', ');
    throw new ApiError(d || `Błąd serwera (${res.status})`, res.status, (data && data.code) || '');
  }
  return data;
}
