// Kartoteka produktów: wyszukiwanie, historia partii, poprawki administratora.
import { api } from '../api.js';
import { closeCamera, scanBar, setScanHandler, openCamera } from '../scanner.js';
import { state } from '../state.js';
import { $, ICON, beep, closeDialog, esc, fmtDate, formDialog, num, openDialog, toast, vatOptions, zl } from '../ui.js';
import { nav, setTitle } from './common.js';

export function viewProducts(view) {
  setTitle('Produkty');
  view.innerHTML = `${scanBar('Szukaj: nazwa, EAN, rozmiar')}<div id="p-list"></div>`;
  const input = $('#scan-input'); input.setAttribute('inputmode', 'search');
  let timer; let seq = 0;
  const search = async () => {
    const q = input.value.trim(); const my = ++seq;
    const box = $('#p-list'); if (!box) return;
    try {
      const list = await api('/api/products?q=' + encodeURIComponent(q));
      if (my !== seq || !$('#p-list')) return; // przyszła nowsza odpowiedź albo zmieniono ekran
      if (!list.length) { box.innerHTML = `<div class="empty">${ICON.tag}<p>${q ? 'Nic nie znaleziono' : 'Kartoteka jest pusta – produkty dodają się same przy zakupach'}</p></div>`; return; }
      box.innerHTML = '<div class="list">' + list.map((p) => `<div class="item clickable" data-id="${p.id}"><div class="row"><div class="grow"><div class="name">${esc(p.name)}</div>
        <div class="meta"><span class="mono">${esc(p.ean)}</span> · SKU ${esc(p.sku)}</div></div>
        <div class="right nowrap"><b>${zl(num(p.price_net))}</b><div class="small muted">netto · ${zl(num(p.price_gross))} brutto</div></div></div></div>`).join('') + '</div>';
      box.onclick = (e) => { const it = e.target.closest('[data-id]'); if (it) productDetail(list.find((x) => x.id === +it.dataset.id)); };
    } catch (e) { box.innerHTML = `<p class="small" style="color:var(--bad)">${esc(e.message)}</p>`; }
  };
  $('#scan-form').onsubmit = (e) => { e.preventDefault(); search(); };
  input.oninput = () => { clearTimeout(timer); timer = setTimeout(search, 300); };
  $('#cam-btn').onclick = openCamera;
  setScanHandler(async (code, cam) => { if (cam) await closeCamera(); input.value = code; beep(true); search(); });
  search();
}

async function productDetail(p) {
  let hist = [];
  try { hist = await api(`/api/variants/${p.id}/history`); } catch (e) { toast(e.message, 'err'); }
  const admin = state.user.is_admin;
  const dlg = openDialog(`<div class="dlg-head">${esc(p.name)}</div><div class="dlg-body">
    <p class="small"><span class="mono">EAN ${esc(p.ean)}</span><br>SKU ${esc(p.sku)} · rozmiar ${esc(p.size || '–')} · kolor ${esc(p.color || '–')}<br>
    Ostatnia cena: <b>${zl(num(p.price_net))}</b> netto (${zl(num(p.price_gross))} brutto, VAT ${esc(p.tax)}${p.tax === 'zw' ? '' : '%'})<br>
    Fakturownia: ${p.fakturownia_product_id ? 'produkt #' + esc(p.fakturownia_product_id) : '<span class="muted">jeszcze nie wysłany</span>'}${p.created_by ? '<br>Dodał(a): ' + esc(p.created_by) : ''}</p>
    <div class="section-title">Partie (zakupy)</div>
    ${hist.length ? `<div class="table-wrap"><table class="preview"><tr><th>Data</th><th>Skąd / kto</th><th>Szt.</th><th>Zostało w drodze</th><th>Netto</th><th>Brutto</th></tr>${hist.map((h) => `<tr>
      <td class="nowrap">${fmtDate(h.bought_at)}</td><td>${esc(h.source_name || (h.source_type === 'nadwyzka' ? 'nadwyżka' : '–'))}<div class="muted">${esc(h.user)}</div></td>
      <td>${h.qty}</td><td>${h.remaining}</td><td class="nowrap">${zl(num(h.price_net))}</td><td class="nowrap">${zl(num(h.price_gross))}</td></tr>`).join('')}</table></div>` : '<p class="small muted">Brak zakupów</p>'}
    </div><div class="dlg-foot"><button class="btn" data-x="close">Zamknij</button>${admin ? '<button class="btn primary" data-x="edit">Edytuj</button>' : ''}</div>`);
  dlg.onclick = async (e) => {
    const x = e.target.closest('[data-x]'); if (!x) return;
    dlg.onclick = null; closeDialog();
    if (x.dataset.x === 'edit') editProduct(p);
  };
}

async function editProduct(p) {
  const v = await formDialog('Edycja produktu', [
    { name: 'name', label: 'Nazwa (model)', value: p.model_name, required: true },
    { name: 'size', label: 'Rozmiar', value: p.size },
    { name: 'color', label: 'Kolor', value: p.color },
    { name: 'ean', label: 'EAN', value: p.ean, inputmode: 'numeric', required: true },
    { name: 'sku', label: 'SKU', value: p.sku, required: true },
    { name: 'price_net', label: 'Ostatnia cena netto (podpowiedź przy zakupie)', value: p.price_net, inputmode: 'decimal' },
    { name: 'tax', label: 'VAT', type: 'select', options: vatOptions, value: p.tax },
    { name: 'fakturownia_product_id', label: 'ID produktu w Fakturowni', value: p.fakturownia_product_id || '', inputmode: 'numeric',
      hint: 'Zmieniaj tylko, gdy produkt już istnieje w Fakturowni' },
  ], { validate: (x) => (!(num(x.price_net) >= 0) ? 'Zła cena' : null) });
  if (!v) return;
  const body = { ...v, price_net: num(v.price_net), fakturownia_product_id: v.fakturownia_product_id.trim() || null };
  try { await api(`/api/variants/${p.id}`, { method: 'PATCH', body }); toast('Zapisano', 'ok'); nav.render(); } catch (err) { toast(err.message, 'err'); }
}
