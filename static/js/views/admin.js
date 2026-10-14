// Panel administratora: stan Fakturowni, ponowne wysyłanie, pracownicy, dziennik.
import { api } from '../api.js';
import { state } from '../state.js';
import { $, esc, fmtDate, formDialog, toast } from '../ui.js';
import { backBtn, bindBack, errorView, loading, nav, setTitle } from './common.js';

const pinField = { name: 'pin', label: 'PIN (4–12 cyfr)', inputmode: 'numeric', required: true };
const pinCheck = (x) => (!/^\d{4,12}$/.test(x.pin) ? 'PIN: 4–12 cyfr' : null);

export async function viewAdmin(view) {
  setTitle('Administracja');
  loading(view);
  let st; let users; let log;
  try {
    [st, users, log] = await Promise.all([api('/api/status'), api('/api/users'), api('/api/sync-log?limit=40')]);
  } catch (e) { return errorView(view, e); }
  const f = st.fakturownia; const un = st.unsynced; const unsum = un.pz + un.mm + un.rw;
  view.innerHTML = `${backBtn()}
    <div class="card"><h2>Fakturownia</h2>
      <p class="small">${f.enabled ? `<span class="tag ok">połączona</span> ${esc(f.domain)}.fakturownia.pl` : '<span class="tag warn">tryb testowy</span> dokumenty nie są wysyłane (FAKTUROWNIA_ENABLED=false)'}<br>
      Magazyny: W drodze #${esc(f.warehouses.transit || '?')} · Główny #${esc(f.warehouses.main || '?')} · Reklamacje #${esc(f.warehouses.returns || '?')}</p>
      <p class="small">Niewysłane: PZ <b>${un.pz}</b> · MM <b>${un.mm}</b> · RW <b>${un.rw}</b> <span class="muted">(ponawiane automatycznie co kilka minut)</span></p>
      <button class="btn sm ${unsum ? 'primary' : ''}" id="retry" ${f.enabled ? '' : 'disabled'}>Wyślij ponownie teraz</button></div>

    <div class="card"><div class="row"><h2 class="grow" style="margin:0">Pracownicy</h2><button class="btn sm primary" id="add-user">Dodaj</button></div>
      ${users.map((u) => `<div class="row" style="border-top:1px solid var(--line);padding:8px 0;margin-top:6px"><div class="grow"><b>${esc(u.name)}</b> ${u.is_admin ? '<span class="tag neutral">admin</span>' : ''} ${u.active ? '' : '<span class="tag bad">wyłączony</span>'}</div>
        <button class="btn sm" data-pin="${u.id}">Zmień PIN</button>${u.id !== state.user.id ? `<button class="btn sm ${u.active ? 'danger' : ''}" data-act="${u.id}" data-on="${u.active ? 0 : 1}">${u.active ? 'Wyłącz' : 'Włącz'}</button>` : ''}</div>`).join('')}</div>

    <div class="section-title">Dziennik Fakturowni</div>
    <div class="list">${log.length ? log.map((l) => `<div class="item"><div class="row"><div class="grow"><div class="small"><b>${esc(l.action)}</b> ${esc(l.ref)}</div><div class="small ${l.ok ? 'muted' : ''}" style="${l.ok ? '' : 'color:var(--bad)'}">${esc(l.message)}</div></div>
      <span class="small muted nowrap">${fmtDate(l.created_at)}</span></div></div>`).join('') : '<div class="item muted small">Pusto</div>'}</div>`;
  bindBack();
  $('#retry').onclick = async () => {
    try { const r = await api('/api/sync/retry', { method: 'POST', timeout: 120000 }); toast(`Sprawdzono: PZ ${r.pz}, MM ${r.mm}, RW ${r.rw}`, 'ok'); nav.render(); } catch (e) { toast(e.message, 'err'); }
  };
  $('#add-user').onclick = async () => {
    const v = await formDialog('Nowy pracownik', [{ name: 'name', label: 'Imię', required: true }, pinField, { name: 'is_admin', label: 'Administrator', type: 'checkbox' }], { validate: pinCheck });
    if (!v) return;
    try { await api('/api/users', { body: v }); toast('Dodano', 'ok'); nav.render(); } catch (e) { toast(e.message, 'err'); }
  };
  view.onclick = async (e) => {
    const pinB = e.target.closest('[data-pin]'); const actB = e.target.closest('[data-act]');
    try {
      if (pinB) {
        const v = await formDialog('Nowy PIN', [pinField], { validate: pinCheck });
        if (v) { await api(`/api/users/${pinB.dataset.pin}`, { method: 'PATCH', body: v }); toast('PIN zmieniony', 'ok'); }
      } else if (actB) {
        await api(`/api/users/${actB.dataset.act}`, { method: 'PATCH', body: { active: actB.dataset.on === '1' } }); nav.render();
      }
    } catch (err) { toast(err.message, 'err'); }
  };
}
