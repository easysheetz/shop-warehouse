// W drodze do magazynu: towar kupiony, jeszcze nieprzyjęty.
import { api } from '../api.js';
import { state } from '../state.js';
import { $, ICON, esc, fmtDate, formDialog, num, toast, zl } from '../ui.js';
import { errorView, loading, nav, setTitle, syncTag } from './common.js';

export async function viewTransit(view) {
  setTitle('W drodze do magazynu');
  loading(view);
  let data;
  try { data = await api('/api/in-transit'); } catch (e) { return errorView(view, e); }
  const mode = state.transitMode || 'produkty';
  view.innerHTML = `
    <div class="totals"><div><b>${data.total_qty}</b><span>sztuk w drodze</span></div><div><b>${zl(num(data.total_value_net))}</b><span>wartość netto</span></div><div><b>${data.purchases.length}</b><span>zakupów</span></div></div>
    <div class="segmented"><button data-m="produkty" class="${mode === 'produkty' ? 'active' : ''}">Wg produktów</button><button data-m="zakupy" class="${mode === 'zakupy' ? 'active' : ''}">Wg zakupów</button></div>
    <div id="transit-body"></div>`;
  $('.segmented', view).onclick = (e) => { const b = e.target.closest('[data-m]'); if (b) { state.transitMode = b.dataset.m; nav.render(); } };
  const body = $('#transit-body');
  if (!data.total_qty) { body.innerHTML = `<div class="empty">${ICON.truck}<p>Nic nie jest w drodze</p></div>`; return; }
  if (mode === 'produkty') {
    body.innerHTML = '<div class="list">' + data.by_product.map((r) => `<div class="item"><div class="row"><div class="grow"><div class="name">${esc(r.variant.name)}</div>
      <div class="meta mono">${esc(r.variant.ean)}</div></div><div class="right"><b>${r.qty} szt.</b><div class="small muted">${zl(num(r.value_net))} netto</div></div></div></div>`).join('') + '</div>';
    return;
  }
  body.innerHTML = data.purchases.map((p) => `
    <div class="card"><div class="row"><div class="grow"><b>${esc(p.source_name || 'Zakup')}</b> ${p.source_type === 'dostawa' ? '<span class="tag neutral">dostawa</span>' : ''}
      <div class="small muted">${fmtDate(p.bought_at)} · ${esc(p.user)}${p.invoice_number ? ' · ' + esc(p.invoice_number) : ''}</div></div>${syncTag(p, p.fakt_doc_number || 'PZ')}</div>
      ${p.sync_error ? `<p class="small" style="color:var(--bad)">${esc(p.sync_error)}</p>` : ''}
      <div style="margin-top:8px">${p.items.filter((i) => i.remaining > 0).map((i) => `
        <div class="row" style="padding:6px 0;border-top:1px solid var(--line)"><div class="grow"><div class="small"><b>${esc(i.variant.name)}</b></div>
          <div class="small muted">${i.remaining} z ${i.qty} szt. · ${zl(num(i.price_net))} netto</div></div>
          ${state.user.is_admin ? `<button class="btn sm" data-wo="${i.id}" data-max="${i.remaining}" data-name="${esc(i.variant.name)}">Odpisz brak</button>` : ''}</div>`).join('')}</div>
    </div>`).join('');
  body.onclick = async (e) => {
    const b = e.target.closest('[data-wo]'); if (!b) return;
    const max = +b.dataset.max;
    const v = await formDialog('Odpis braku', [
      { name: 'qty', label: `Ile sztuk odpisać? (max ${max})`, inputmode: 'numeric', value: String(max), required: true },
      { name: 'reason', label: 'Powód', required: true, placeholder: 'np. zgubione, sklep nie wydał' },
    ], { okLabel: 'Odpisz', intro: `<p class="small muted">${esc(b.dataset.name)} – towar zniknie z „W drodze”, a w Fakturowni powstanie dokument RW.</p>`,
      validate: (x) => (!(parseInt(x.qty, 10) >= 1 && parseInt(x.qty, 10) <= max) ? `Podaj od 1 do ${max}` : x.reason.length < 2 ? 'Podaj powód' : null) });
    if (!v) return;
    try {
      const r = await api(`/api/items/${b.dataset.wo}/writeoff`, { body: { qty: parseInt(v.qty, 10), reason: v.reason } });
      toast(r.sync_status === 'blad' ? 'Odpisano, ale RW nie dotarło do Fakturowni: ' + r.sync_error : 'Odpisano', r.sync_status === 'blad' ? 'err' : 'ok');
      nav.render();
    } catch (err) { toast(err.message, 'err'); }
  };
}
