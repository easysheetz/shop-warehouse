// Zakładka „Więcej”: dostawa, reklamacje, historia, administracja, wylogowanie.
import { api } from '../api.js';
import { state } from '../state.js';
import { $, ICON, confirmDialog, esc, fmtDate, formDialog, num, toast, zl } from '../ui.js';
import { viewAdmin } from './admin.js';
import { viewCart } from './cart.js';
import { backBtn, bindBack, errorView, loading, nav, setTitle } from './common.js';

export let logoutHandler = () => {};
export function setLogoutHandler(fn) { logoutHandler = fn; }

export async function viewMore(view) {
  if (state.sub === 'dostawa') return viewCart(view, 'dostawa');
  if (state.sub === 'reklamacje') return viewComplaints(view);
  if (state.sub === 'historia') return viewHistory(view);
  if (state.sub === 'admin' && state.user.is_admin) return viewAdmin(view);
  setTitle('Więcej');
  let st = null;
  try { st = await api('/api/status'); } catch { /* menu działa i bez liczników */ }
  view.innerHTML = `<div class="list menu-list">
    <button data-sub="dostawa">${ICON.file}<span class="grow">Dostawa ręczna / z pliku CSV</span></button>
    <button data-sub="reklamacje">${ICON.alert}<span class="grow">Reklamacje</span>${st && st.open_complaints ? `<span class="tag bad">${st.open_complaints}</span>` : ''}</button>
    <button data-sub="historia">${ICON.list}<span class="grow">Historia zakupów</span></button>
    ${state.user.is_admin ? `<button data-sub="admin">${ICON.gear}<span class="grow">Administracja</span>${st && (st.unsynced.pz + st.unsynced.mm + st.unsynced.rw) ? '<span class="tag warn">do wysłania</span>' : ''}</button>` : ''}
    <button data-sub="logout">${ICON.out}<span class="grow">Wyloguj (${esc(state.user.name)})</span></button></div>
    ${st ? `<p class="small muted" style="text-align:center">Produktów w kartotece: ${st.products}${st.environment !== 'production' ? ` · środowisko: ${esc(st.environment)}` : ''}</p>` : ''}`;
  $('.menu-list').onclick = async (e) => {
    const b = e.target.closest('[data-sub]'); if (!b) return;
    if (b.dataset.sub === 'logout') {
      if (await confirmDialog('Wylogować?', '<p>Otwarte koszyki zostają na serwerze – po ponownym zalogowaniu będą na miejscu.</p>', 'Wyloguj')) logoutHandler();
      return;
    }
    nav.go('wiecej', b.dataset.sub);
  };
}

async function viewComplaints(view) {
  setTitle('Reklamacje');
  const st = state.complaintStatus || 'otwarta';
  loading(view);
  let list;
  try { list = await api('/api/complaints?status=' + st); } catch (e) { return errorView(view, e); }
  view.innerHTML = `${backBtn()}<div class="segmented"><button data-s="otwarta" class="${st === 'otwarta' ? 'active' : ''}">Otwarte</button><button data-s="zamknieta" class="${st === 'zamknieta' ? 'active' : ''}">Zamknięte</button></div>
    ${list.length ? list.map((c) => `<div class="card"><div class="row"><div class="grow"><b>${esc(c.variant.name)}</b><div class="small muted mono">${esc(c.variant.ean)}</div></div><b>${c.qty} szt.</b></div>
      <p style="margin:8px 0"><span class="tag bad">usterka</span> ${esc(c.note)}</p>
      <p class="small muted">Kupione: ${esc(c.source_name || '–')} · ${fmtDate(c.bought_at)} · ${esc(c.bought_by)} · ${zl(num(c.price_net))} netto${c.invoice_number ? ' · FV ' + esc(c.invoice_number) : ''}<br>Zgłoszono: ${fmtDate(c.created_at)}</p>
      ${c.resolution ? `<p class="small"><b>Rozwiązanie:</b> ${esc(c.resolution)}</p>` : ''}
      ${st === 'otwarta' && state.user.is_admin ? `<button class="btn sm" data-close="${c.id}">Zamknij reklamację</button>` : ''}</div>`).join('') : `<div class="empty">${ICON.alert}<p>Brak reklamacji</p></div>`}`;
  bindBack();
  $('.segmented', view).onclick = (e) => { const b = e.target.closest('[data-s]'); if (b) { state.complaintStatus = b.dataset.s; nav.render(); } };
  view.onclick = async (e) => {
    const b = e.target.closest('[data-close]'); if (!b) return;
    const v = await formDialog('Zamknij reklamację', [{ name: 'resolution', label: 'Jak rozwiązano?', type: 'textarea', required: true, placeholder: 'np. zwrot do sklepu, naprawione, utylizacja' }],
      { validate: (x) => (x.resolution.length < 2 ? 'Opisz rozwiązanie' : null) });
    if (!v) return;
    try { await api(`/api/complaints/${b.dataset.close}/close`, { body: v }); toast('Zamknięto', 'ok'); nav.render(); } catch (err) { toast(err.message, 'err'); }
  };
}

const STATUS = { w_drodze: ['w drodze', 'warn'], czesciowo: ['częściowo', 'warn'], przyjety: ['przyjęty', 'ok'], zamkniety: ['zamknięty', 'neutral'] };

async function viewHistory(view) {
  setTitle('Historia zakupów');
  const mine = state.histMine ?? !state.user.is_admin;
  loading(view);
  let list;
  try { list = await api('/api/purchases?limit=100' + (mine ? '&mine=true' : '')); } catch (e) { return errorView(view, e); }
  view.innerHTML = `${backBtn()}<div class="segmented"><button data-m="1" class="${mine ? 'active' : ''}">Moje</button><button data-m="0" class="${!mine ? 'active' : ''}">Wszystkie</button></div>
    ${list.length ? '<div class="list">' + list.map((p) => `<div class="item"><div class="row"><div class="grow"><div class="name">${esc(p.source_name || (p.source_type === 'nadwyzka' ? 'Nadwyżka z przyjęcia' : 'Zakup'))}</div>
      <div class="meta">${fmtDate(p.bought_at)} · ${esc(p.user)} · ${p.total_qty} szt. · ${zl(num(p.total_net))} netto / ${zl(num(p.total_gross))} brutto</div>
      ${p.fakt_doc_number ? `<div class="meta">${esc(p.fakt_doc_number)}</div>` : ''}${p.sync_error ? `<div class="small" style="color:var(--bad)">${esc(p.sync_error)}</div>` : ''}</div>
      <span class="tag ${(STATUS[p.status] || ['', 'neutral'])[1]}">${esc((STATUS[p.status] || [p.status])[0])}</span></div></div>`).join('') + '</div>' : `<div class="empty">${ICON.list}<p>Brak zakupów</p></div>`}`;
  bindBack();
  $('.segmented', view).onclick = (e) => { const b = e.target.closest('[data-m]'); if (b) { state.histMine = b.dataset.m === '1'; nav.render(); } };
}
