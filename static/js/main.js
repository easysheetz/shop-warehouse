// Start aplikacji: logowanie, zakładki, przełączanie ekranów.
import { api, checkConnection, setUnauthorizedHandler } from './api.js';
import { closeCamera, setScanHandler } from './scanner.js';
import { cleanupLegacyStorage, clearSession, saveSession, state, store } from './state.js';
import { $, $$, ICON, beep, closeDialog, esc } from './ui.js';
import { viewCart } from './views/cart.js';
import { nav } from './views/common.js';
import { setLogoutHandler, viewMore } from './views/more.js';
import { viewProducts } from './views/products.js';
import { viewReceipt } from './views/receipt.js';
import { viewTransit } from './views/transit.js';

const TABS = [
  { id: 'zakup', label: 'Zakup', icon: ICON.cart, view: (v) => viewCart(v, 'sklep') },
  { id: 'wdrodze', label: 'W drodze', icon: ICON.truck, view: viewTransit },
  { id: 'przyjecie', label: 'Przyjęcie', icon: ICON.box, view: viewReceipt },
  { id: 'produkty', label: 'Produkty', icon: ICON.tag, view: viewProducts },
  { id: 'wiecej', label: 'Więcej', icon: ICON.more, view: viewMore },
];

// ------------------------------------------------------------------ nawigacja
function go(tab, sub = null) {
  state.tab = tab; state.sub = sub;
  $$('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  window.scrollTo(0, 0);
  render();
}

function render() {
  clearInterval(state.pollTimer); state.pollTimer = null;
  setScanHandler(null);
  const view = $('#view');
  view.onclick = null;
  const t = TABS.find((x) => x.id === state.tab) || TABS[0];
  t.view(view);
}

nav.go = go;
nav.render = render;

// ------------------------------------------------------------------ logowanie
let pin = ''; let loginName = '';

function renderPin() {
  $('#pin-dots').innerHTML = Array.from({ length: Math.max(4, pin.length) }, (_, i) => `<i class="${i < pin.length ? 'on' : ''}"></i>`).join('');
}

async function showLogin() {
  $('#app').classList.add('hidden'); $('#login').classList.remove('hidden');
  pin = ''; renderPin();
  const pad = $('#pin-pad');
  pad.innerHTML = [1, 2, 3, 4, 5, 6, 7, 8, 9, '⌫', 0, 'OK'].map((k) => `<button type="button" data-k="${k}">${k}</button>`).join('');
  pad.onclick = (e) => {
    const k = e.target.closest('[data-k]')?.dataset.k; if (k === undefined) return;
    if (k === '⌫') pin = pin.slice(0, -1);
    else if (k === 'OK') { doLogin(); return; } else if (pin.length < 12) pin += k;
    renderPin();
  };
  const box = $('#login-names'); const nameInput = $('#login-name');
  let names = [];
  try { names = await api('/api/users/names'); } catch (e) { $('#login-error').textContent = e.message; }
  if (names.length) {
    box.innerHTML = names.map((n) => `<button type="button" data-n="${esc(n)}">${esc(n)}</button>`).join('');
    box.onclick = (e) => {
      const b = e.target.closest('[data-n]'); if (!b) return;
      loginName = b.dataset.n; store.write('lastName', loginName);
      $$('#login-names button').forEach((x) => x.classList.toggle('active', x === b));
    };
    const last = store.read('lastName');
    if (last && names.includes(last)) { loginName = last; $$('#login-names button').forEach((x) => x.classList.toggle('active', x.dataset.n === last)); }
    nameInput.classList.add('hidden');
  } else { box.innerHTML = ''; nameInput.classList.remove('hidden'); }
}

async function doLogin() {
  const name = loginName || $('#login-name').value.trim();
  $('#login-error').textContent = '';
  if (!name) { $('#login-error').textContent = 'Wybierz swoje imię'; return; }
  if (pin.length < 4) { $('#login-error').textContent = 'Wpisz PIN'; return; }
  try {
    const r = await api('/api/login', { body: { name, pin } });
    saveSession(r.token, r.user);
    startApp();
  } catch (e) { $('#login-error').textContent = e.message; pin = ''; renderPin(); beep(false); }
}

// klawiatura komputera przy logowaniu
document.addEventListener('keydown', (e) => {
  if ($('#login').classList.contains('hidden') || e.target.tagName === 'INPUT') return;
  if (/^\d$/.test(e.key) && pin.length < 12) { pin += e.key; renderPin(); } else if (e.key === 'Backspace') { pin = pin.slice(0, -1); renderPin(); } else if (e.key === 'Enter') doLogin();
});

async function logout() {
  clearInterval(state.pollTimer); state.pollTimer = null;
  setScanHandler(null); closeDialog(); await closeCamera();
  clearSession(); state.tab = 'zakup'; state.sub = null;
  showLogin();
}

// ------------------------------------------------------------------ start
async function startApp() {
  $('#login').classList.add('hidden'); $('#app').classList.remove('hidden');
  $('#tabs').innerHTML = TABS.map((t) => `<button type="button" data-tab="${t.id}">${t.icon}<span>${t.label}</span></button>`).join('');
  $('#tabs').onclick = (e) => { const b = e.target.closest('[data-tab]'); if (b) go(b.dataset.tab); };
  $('#user-name').textContent = state.user.name;
  go(state.tab);
  // odśwież dane użytkownika (np. zmiana uprawnień przez admina)
  try { const me = await api('/api/me'); saveSession(state.token, me); $('#user-name').textContent = me.name; } catch { /* 401 obsłuży logout */ }
}

setUnauthorizedHandler(logout);
setLogoutHandler(logout);
$('#netbar-retry').onclick = async () => { if (await checkConnection()) render(); };
cleanupLegacyStorage();
checkConnection();
if (state.token && state.user) startApp(); else showLogin();
