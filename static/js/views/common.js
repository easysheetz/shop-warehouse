// Elementy wspólne dla ekranów.
import { $, ICON, esc } from '../ui.js';

// Nawigacja – funkcje ustawia main.js (unikamy zależności cyklicznych)
export const nav = { go: () => {}, render: () => {} };

export function setTitle(t) { $('#title').textContent = t; }
export function loading(view) { view.innerHTML = '<div class="empty muted">Ładowanie…</div>'; }
export function errorView(view, e) {
  view.innerHTML = `<div class="empty">${ICON.alert}<p>${esc(e.message)}</p><button class="btn" id="err-retry">Spróbuj ponownie</button></div>`;
  $('#err-retry').onclick = () => nav.render();
}
export function backBtn() { return '<button class="btn sm" id="back" style="margin-bottom:12px">← Więcej</button>'; }
export function bindBack() { const b = $('#back'); if (b) b.onclick = () => nav.go('wiecej'); }

export const syncTag = (o, number) => {
  if (o.sync_status === 'ok') return `<span class="tag ok">${esc(number || 'OK')}</span>`;
  if (o.sync_status === 'blad') return '<span class="tag bad">błąd Fakturowni</span>';
  if (o.sync_status === 'wylaczone') return '<span class="tag neutral">tryb testowy</span>';
  return '<span class="tag warn">czeka</span>';
};
