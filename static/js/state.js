// Wspólny stan aplikacji. W przeglądarce trzymamy tylko sesję logowania i drobne wygody
// (ostatnie sklepy) – wszystkie dane zakupów są na serwerze.
const read = (k, d = null) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* tryb prywatny */ } };
const remove = (k) => { try { localStorage.removeItem(k); } catch { /* tryb prywatny */ } };

export const store = { read, write, remove };

export const state = {
  token: read('token'),
  user: read('user'),
  tab: 'zakup',
  sub: null,
  online: navigator.onLine,
  pollTimer: null,
  receipt: null,
  lastScanHtml: '',
  complaintMode: false,
};

export function saveSession(token, user) {
  state.token = token; state.user = user;
  write('token', token); write('user', user);
}

export function clearSession() {
  state.token = null; state.user = null;
  remove('token'); remove('user');
}

// Dane z poprzedniej wersji (tryb offline) – już nieużywane
export function cleanupLegacyStorage() {
  ['catalog', 'localProducts', 'outbox', 'draft_sklep', 'draft_dostawa'].forEach(remove);
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => r.unregister())).catch(() => {});
  }
}
