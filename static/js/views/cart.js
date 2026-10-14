// Zakup w sklepie i dostawa z innego źródła. Koszyk jest na serwerze – każdy skan zapisuje się od razu.
import { api } from '../api.js';
import { bindScanBar, camInfo, closeCamera, scanBar, setScanHandler } from '../scanner.js';
import { store } from '../state.js';
import {
  $, ICON, beep, confirmDialog, esc, fmtDate, formDialog, grossHint, num, round2, toast, vatOptions, zl,
} from '../ui.js';
import { errorView, loading, nav, setTitle } from './common.js';

const LABEL = {
  sklep: { title: 'Zakup w sklepie', finish: 'Zakończ zakup', cancel: 'Anuluj zakup' },
  dostawa: { title: 'Dostawa z innego źródła', finish: 'Zapisz dostawę', cancel: 'Anuluj dostawę' },
};

let cart = null;          // aktualny koszyk z serwera
let scanChain = Promise.resolve(); // skany wysyłane po kolei (szybki czytnik)

export async function viewCart(view, kind) {
  setTitle(LABEL[kind].title);
  loading(view);
  try { cart = await api(`/api/carts/${kind}`); } catch (e) { return errorView(view, e); }
  if (!cart) return startForm(view, kind);

  view.innerHTML = `
    <div class="row" style="margin-bottom:10px"><div class="grow"><b>${esc(cart.source_name || 'Zakup')}</b>
      <div class="small muted">${kind === 'dostawa' ? (cart.invoice_number ? 'faktura ' + esc(cart.invoice_number) : 'bez numeru faktury') : 'rozpoczęty ' + fmtDate(cart.created_at)}</div></div>
      ${kind === 'dostawa' ? '<button class="btn sm" id="back">← Więcej</button>' : '<button class="btn sm" id="edit-head">Zmień sklep</button>'}</div>
    ${scanBar(kind === 'dostawa' ? 'Wpisz lub zeskanuj EAN' : 'Zeskanuj lub wpisz EAN')}
    ${kind === 'dostawa' ? `<div class="btn-row" style="margin-bottom:12px"><button class="btn" id="csv-btn">${ICON.file.replace('<svg', '<svg width="18" height="18" style="vertical-align:-3px"')} Wczytaj plik CSV</button><button class="btn" id="tpl-btn">Wzór pliku</button></div>
      <input type="file" id="csv-file" accept=".csv,text/csv,text/plain" class="hidden">` : ''}
    <div class="totals" id="cart-totals"></div>
    <div id="cart-items"></div>
    <div class="btn-row"><button class="btn danger" id="cancel">${LABEL[kind].cancel}</button><button class="btn primary" id="finish">${LABEL[kind].finish}</button></div>`;
  bindScanBar();
  renderItems();
  // skany po kolei (szybki czytnik); błąd jednego skanu nie blokuje następnych
  setScanHandler((code, cam) => { const run = scanChain.then(() => scan(code, cam)); scanChain = run.catch(() => {}); return run; });

  $('#finish').onclick = () => finish(kind);
  $('#cancel').onclick = async () => {
    if (!(await confirmDialog(LABEL[kind].cancel + '?', '<p>Wszystkie pozycje zostaną usunięte.</p>', LABEL[kind].cancel, 'danger'))) return;
    try { await api(`/api/purchases/${cart.id}`, { method: 'DELETE' }); nav.render(); } catch (e) { toast(e.message, 'err'); }
  };
  if (kind === 'dostawa') {
    $('#back').onclick = () => nav.go('wiecej');
    $('#tpl-btn').onclick = downloadTemplate;
    $('#csv-btn').onclick = () => $('#csv-file').click();
    $('#csv-file').onchange = importCsv;
  } else {
    $('#edit-head').onclick = async () => {
      const v = await formDialog('Sklep', [{ name: 's', label: 'Nazwa sklepu', value: cart.source_name }]);
      if (!v) return;
      try { cart = await api(`/api/purchases/${cart.id}`, { method: 'PATCH', body: { source_name: v.s } }); nav.render(); } catch (e) { toast(e.message, 'err'); }
    };
  }
}

function startForm(view, kind) {
  setScanHandler(null);
  const stores = store.read('stores', []);
  if (kind === 'sklep') {
    view.innerHTML = `<div class="card"><h2>Nowy zakup</h2>
      <label class="field"><span>Sklep</span><input type="text" id="src" list="dl-stores" placeholder="np. Decathlon Kraków" autocomplete="off">
      <datalist id="dl-stores">${stores.map((s) => `<option value="${esc(s)}">`).join('')}</datalist></label>
      <button class="btn primary big block" id="start">Rozpocznij zakup</button></div>`;
  } else {
    view.innerHTML = `<button class="btn sm" id="back" style="margin-bottom:12px">← Więcej</button>
      <div class="card"><h2>Nowa dostawa</h2>
      <p class="small muted">Dla towaru kupionego poza sklepem (hurtownia, zamówienie online), którego nie dało się zeskanować przy zakupie.</p>
      <label class="field"><span>Źródło / dostawca</span><input type="text" id="src" placeholder="np. Hurtownia X"></label>
      <label class="field"><span>Numer faktury (opcjonalnie)</span><input type="text" id="inv" placeholder="np. FV 123/10/2026"></label>
      <button class="btn primary big block" id="start">Rozpocznij dostawę</button></div>`;
    $('#back').onclick = () => nav.go('wiecej');
  }
  $('#start').onclick = async () => {
    const src = $('#src').value.trim();
    if (kind === 'sklep' && src) store.write('stores', [src, ...stores.filter((x) => x !== src)].slice(0, 15));
    try {
      await api(`/api/carts/${kind}`, { body: { source_name: src, invoice_number: kind === 'dostawa' ? $('#inv').value.trim() : '' } });
      nav.render();
    } catch (e) { toast(e.message, 'err'); }
  };
}

async function newProductDialog(ean) {
  let names = [];
  try { names = await api('/api/models/names'); } catch { /* bez podpowiedzi */ }
  return formDialog('Nowy produkt', [
    { name: 'name', label: 'Nazwa produktu', required: true, list: 'dl-names', listValues: names, placeholder: 'np. Bluza Nike Club' },
    { name: 'size', label: 'Rozmiar', placeholder: 'np. M, 42, uni' },
    { name: 'color', label: 'Kolor (opcjonalnie)' },
    { name: 'price_net', label: 'Cena zakupu NETTO za sztukę', required: true, inputmode: 'decimal', hint: '&nbsp;' },
    { name: 'tax', label: 'VAT', type: 'select', options: vatOptions, value: '23' },
  ], {
    okLabel: 'Dodaj',
    intro: `<p class="small muted">EAN <span class="mono">${esc(ean)}</span> nie ma jeszcze w bazie. Wpisz dane raz – następnym razem system je zapamięta.</p>`,
    onInput: grossHint,
    validate: (x) => (!x.name ? 'Podaj nazwę' : !(num(x.price_net) >= 0) ? 'Podaj poprawną cenę netto' : null),
  });
}

async function scan(code, fromCamera) {
  let res;
  try {
    res = await api(`/api/purchases/${cart.id}/items`, { body: { ean: code } });
  } catch (e) {
    if (e.code !== 'unknown_ean') throw e;
    if (fromCamera) await closeCamera();
    beep(true);
    const p = await newProductDialog(code);
    if (!p) return;
    res = await api(`/api/purchases/${cart.id}/items`, { body: {
      ean: code, price_net: p.price_net, tax: p.tax, new_product: { name: p.name, size: p.size, color: p.color } } });
  }
  cart = res.purchase;
  beep(true);
  const it = cart.items.find((i) => i.id === res.item_id);
  if (fromCamera && it) camInfo(`+1 ${it.variant.name} (razem ${it.qty})`);
  renderItems(res.item_id);
}

function renderItems(flashId = null) {
  const box = $('#cart-items'); if (!box || !cart) return;
  $('#cart-totals').innerHTML = `<div><b>${cart.total_qty}</b><span>sztuk</span></div><div><b>${zl(num(cart.total_net))}</b><span>netto</span></div><div><b>${zl(num(cart.total_gross))}</b><span>brutto</span></div>`;
  if (!cart.items.length) { box.innerHTML = `<div class="empty">${ICON.cam}<p>Zeskanuj pierwszy produkt</p></div>`; return; }
  box.innerHTML = '<div class="list">' + [...cart.items].reverse().map((i) => `
    <div class="item ${i.id === flashId ? 'flash' : ''}" data-id="${i.id}">
      <div class="row"><div class="grow"><div class="name">${esc(i.variant.name)} ${i.is_new_product ? '<span class="tag warn">nowy</span>' : ''}</div>
        <div class="meta mono">${esc(i.variant.ean)}</div></div>
        <button class="price-btn" data-act="price"><b>${zl(num(i.price_net))}</b><span class="small muted">netto · ${esc(i.tax)}%</span></button></div>
      <div class="row" style="margin-top:8px"><div class="qty"><button data-act="minus" aria-label="mniej">−</button><span>${i.qty}</span><button data-act="plus" aria-label="więcej">+</button></div>
        <div class="grow right small muted">brutto ${zl(num(i.price_gross))} · razem ${zl(num(i.value_gross))}</div></div>
    </div>`).join('') + '</div>';
  box.onclick = onItemClick;
}

async function onItemClick(e) {
  const btn = e.target.closest('[data-act]'); if (!btn) return;
  const id = +btn.closest('[data-id]').dataset.id;
  const it = cart.items.find((x) => x.id === id); if (!it) return;
  let body;
  if (btn.dataset.act === 'plus') body = { qty: it.qty + 1 };
  else if (btn.dataset.act === 'minus') {
    if (it.qty > 1) body = { qty: it.qty - 1 };
    else if (await confirmDialog('Usunąć pozycję?', `<p>${esc(it.variant.name)}</p>`, 'Usuń', 'danger')) body = { qty: 0 };
    else return;
  } else {
    const v = await formDialog('Cena zakupu', [
      { name: 'price_net', label: 'Cena NETTO za sztukę', inputmode: 'decimal', value: it.price_net, required: true, hint: '&nbsp;' },
      { name: 'tax', label: 'VAT', type: 'select', options: vatOptions, value: it.tax },
      ...(it.qty > 1 ? [{ name: 'count', label: `Ilu sztuk dotyczy ta cena? (z ${it.qty})`, inputmode: 'numeric', value: String(it.qty), hint: 'Mniej sztuk = osobna partia z inną ceną' }] : []),
    ], {
      intro: `<p class="small muted">${esc(it.variant.name)}</p>`,
      onInput: grossHint,
      validate: (x) => (!(num(x.price_net) >= 0) ? 'Podaj poprawną cenę'
        : x.count !== undefined && !(parseInt(x.count, 10) >= 1 && parseInt(x.count, 10) <= it.qty) ? `Podaj liczbę od 1 do ${it.qty}` : null),
    });
    if (!v) return;
    const count = v.count ? parseInt(v.count, 10) : it.qty;
    body = { price_net: round2(num(v.price_net)).toFixed(2), tax: v.tax, ...(count < it.qty ? { split_qty: count } : {}) };
  }
  try {
    cart = await api(`/api/purchases/${cart.id}/items/${id}`, { method: 'PATCH', body });
    renderItems();
  } catch (err) { toast(err.message, 'err'); }
}

async function finish(kind) {
  if (!cart.items.length) { toast('Koszyk jest pusty', 'err'); return; }
  const ok = await confirmDialog(kind === 'sklep' ? 'Zakończyć zakup?' : 'Zapisać dostawę?',
    `<p><b>${cart.total_qty} szt.</b> · ${zl(num(cart.total_net))} netto · ${zl(num(cart.total_gross))} brutto</p>
     <p class="small muted">Towar trafi do zakładki „W drodze”, a w Fakturowni powstanie dokument PZ.</p>`, LABEL[kind].finish);
  if (!ok) return;
  try {
    const p = await api(`/api/purchases/${cart.id}/finish`, { method: 'POST', timeout: 60000 });
    if (p.sync_status === 'ok') toast(`Zapisano ✓ ${p.fakt_doc_number}`, 'ok');
    else if (p.sync_status === 'wylaczone') toast('Zapisano (tryb testowy – bez Fakturowni)', 'ok');
    else toast('Zapisano. Fakturownia: ' + (p.sync_error || 'wyśle się później'), 'err');
    kind === 'dostawa' ? nav.go('wiecej') : nav.render();
  } catch (e) { toast(e.message, 'err'); }
}

function downloadTemplate() {
  const csv = '﻿ean;nazwa;rozmiar;kolor;ilosc;cena_netto;vat\n5901234567890;Bluza Nike Club;M;czarny;3;89,00;23\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'wzor-dostawy.csv'; a.click();
}

async function importCsv(e) {
  const file = e.target.files[0]; e.target.value = '';
  if (!file) return;
  const fd = new FormData(); fd.append('file', file);
  let r;
  try { r = await api('/api/import/csv', { body: fd, timeout: 60000 }); } catch (err) { toast(err.message, 'err'); return; }
  const tag = (s) => (s === 'znany' ? '<span class="tag ok">w bazie</span>' : s === 'nowy' ? '<span class="tag warn">nowy</span>' : '<span class="tag bad">błąd</span>');
  const ok = await confirmDialog(`Podgląd pliku (${r.rows.length} wierszy)`, `
    <p class="small">Poprawne: <b>${r.ok}</b> · z błędami: <b style="color:var(--bad)">${r.errors}</b> (zostaną pominięte)</p>
    <div class="table-wrap"><table class="preview"><tr><th>#</th><th>Produkt</th><th>Szt.</th><th>Netto</th><th></th></tr>
    ${r.rows.map((x) => `<tr><td>${x.line}</td><td>${esc(x.known_name || [x.name, x.size, x.color].filter(Boolean).join(' – ') || '—')}<div class="mono muted">${esc(x.ean)}</div>
      ${x.errors.length ? `<div style="color:var(--bad)">${esc(x.errors.join(', '))}</div>` : ''}</td><td>${x.qty ?? '–'}</td><td class="nowrap">${x.price_net ? zl(num(x.price_net)) : '–'}</td><td>${tag(x.status)}</td></tr>`).join('')}
    </table></div>`, `Dodaj ${r.ok} poprawnych`);
  if (!ok || !r.ok) return;
  const items = r.rows.filter((x) => x.status !== 'blad').map((x) => ({
    ean: x.ean, qty: x.qty, price_net: x.price_net, tax: x.tax,
    ...(x.status === 'nowy' && x.name ? { new_product: { name: x.name, size: x.size, color: x.color } } : {}),
  }));
  try {
    cart = await api(`/api/purchases/${cart.id}/items/bulk`, { body: { items }, timeout: 60000 });
    toast(`Dodano ${items.length} pozycji`, 'ok');
    renderItems();
  } catch (err) { toast(err.message, 'err'); }
}
