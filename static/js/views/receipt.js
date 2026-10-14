// Przyjęcie na magazyn – wspólne dla wszystkich, porównanie z „W drodze”, reklamacje.
import { api } from '../api.js';
import { bindScanBar, camInfo, closeCamera, scanBar, setScanHandler } from '../scanner.js';
import { state } from '../state.js';
import { $, $$, ICON, beep, confirmDialog, esc, fmtDate, formDialog, num, toast, zl } from '../ui.js';
import { errorView, loading, nav, setTitle, syncTag } from './common.js';

export async function viewReceipt(view) {
  setTitle('Przyjęcie na magazyn');
  loading(view);
  let r;
  try { r = await api('/api/receipts/current'); } catch (e) { return errorView(view, e); }
  if (!r) {
    view.innerHTML = `<div class="card"><h2>Przyjęcie towaru</h2><p class="muted small">Zeskanuj wszystko, co przywieźliście. Program porówna to z listą „W drodze”, a po zatwierdzeniu przesunie towar w Fakturowni do magazynu głównego (lub reklamacji).</p>
      <button class="btn primary big block" id="start">Rozpocznij przyjęcie</button></div>${await historyHtml()}`;
    $('#start').onclick = async () => { try { await api('/api/receipts', { method: 'POST' }); nav.render(); } catch (e) { toast(e.message, 'err'); } };
    return;
  }
  state.receipt = r;
  const complaint = !!state.complaintMode;
  view.innerHTML = `
    <label class="toggle ${complaint ? 'on' : ''}" id="cmode"><input type="checkbox" ${complaint ? 'checked' : ''}> Tryb reklamacji – kolejne skany idą do magazynu „Reklamacje”</label>
    ${scanBar(complaint ? 'Zeskanuj produkt z usterką' : 'Zeskanuj produkt')}
    <div id="last-scan">${state.lastScanHtml || ''}</div>
    <div class="totals" id="r-totals"></div>
    <div class="segmented" id="r-mode"><button data-m="porownanie">Porównanie</button><button data-m="zeskanowane">Zeskanowane</button></div>
    <div id="r-body"></div>
    <button class="btn primary big block" id="confirm" style="margin-top:6px">Zatwierdź przyjęcie</button>
    <p class="small muted" style="text-align:center">Rozpoczął(a): ${esc(r.user)} · ${fmtDate(r.created_at)} · kilka osób może skanować jednocześnie</p>`;
  bindScanBar();
  $('#cmode input').onchange = (e) => { state.complaintMode = e.target.checked; nav.render(); };
  $('#r-mode').onclick = (e) => { const b = e.target.closest('[data-m]'); if (b) { state.receiptMode = b.dataset.m; renderBody(); } };
  $('#confirm').onclick = confirmReceipt;
  renderBody();
  setScanHandler(scan);
  // odśwież co kilka sekund – widać skany drugiej osoby
  state.pollTimer = setInterval(async () => {
    if ($('#dlg').open || state.tab !== 'przyjecie' || !state.online) return;
    try {
      const fresh = await api('/api/receipts/current');
      if (fresh && fresh.id === state.receipt.id) { state.receipt = fresh; renderBody(); } else if (!fresh) nav.render();
    } catch { /* spróbujemy za chwilę */ }
  }, 6000);
}

function renderBody() {
  const r = state.receipt; const body = $('#r-body'); if (!body) return;
  const mode = state.receiptMode || 'porownanie';
  $$('#r-mode button').forEach((b) => b.classList.toggle('active', b.dataset.m === mode));
  const damaged = r.lines.filter((l) => l.damaged).reduce((s, l) => s + l.qty, 0);
  $('#r-totals').innerHTML = `<div><b>${r.total_qty - damaged}</b><span>dobre</span></div><div><b style="color:${damaged ? 'var(--bad)' : 'inherit'}">${damaged}</b><span>reklamacje</span></div>
    <div><b style="color:${r.missing_qty ? 'var(--warn)' : 'inherit'}">${r.missing_qty}</b><span>brakuje</span></div>`;
  if (mode === 'porownanie') {
    if (!r.compare.length) { body.innerHTML = `<div class="empty">${ICON.box}<p>Nic nie jest w drodze i nic nie zeskanowano</p></div>`; return; }
    body.innerHTML = '<div class="list">' + r.compare.map((c) => {
      const cls = c.diff === 0 ? 'ok' : c.diff < 0 ? 'warn' : 'bad';
      const txt = c.diff === 0 ? 'zgadza się' : c.diff < 0 ? `brakuje ${-c.diff}` : `nadwyżka ${c.diff}`;
      return `<div class="item"><div class="row"><div class="grow"><div class="name">${esc(c.variant.name)}</div><div class="meta mono">${esc(c.variant.ean)}</div>
        ${c.diff > 0 ? `<div class="small" style="color:var(--warn)">Nadwyżka wejdzie z ostatnią ceną ${zl(num(c.surplus_price_net))} netto</div>` : ''}</div>
        <div class="right"><b>${c.scanned} / ${c.expected}</b><div><span class="tag ${cls}">${txt}</span></div></div></div></div>`;
    }).join('') + '</div><p class="small muted">Brakujące sztuki zostaną w „W drodze”. Jeśli na pewno nie dotrą, administrator może je odpisać.</p>';
    return;
  }
  if (!r.lines.length) { body.innerHTML = `<div class="empty">${ICON.cam}<p>Nic jeszcze nie zeskanowano</p></div>`; return; }
  body.innerHTML = '<div class="list">' + r.lines.map((l) => `<div class="item"><div class="row"><div class="grow"><div class="name">${esc(l.variant.name)} ${l.damaged ? '<span class="tag bad">reklamacja</span>' : ''}</div>
    ${l.damaged ? `<div class="small">${esc(l.note)}</div>` : ''}<div class="meta mono">${esc(l.variant.ean)}</div></div>
    <div class="right"><b>${l.qty} szt.</b><div><button class="btn sm" data-edit="${l.id}">Zmień</button></div></div></div></div>`).join('') + '</div>';
  body.onclick = async (e) => {
    const b = e.target.closest('[data-edit]'); if (!b) return;
    const l = state.receipt.lines.find((x) => x.id === +b.dataset.edit);
    const fields = [{ name: 'qty', label: 'Ilość (0 = usuń)', inputmode: 'numeric', value: String(l.qty), required: true }];
    if (l.damaged) fields.push({ name: 'note', label: 'Opis usterki', type: 'textarea', value: l.note });
    const v = await formDialog(l.variant.name, fields, { validate: (x) => (!(parseInt(x.qty, 10) >= 0) ? 'Podaj ilość' : null) });
    if (!v) return;
    try {
      state.receipt = await api(`/api/receipts/${state.receipt.id}/lines/${l.id}`, { method: 'PATCH', body: { qty: parseInt(v.qty, 10), ...(l.damaged ? { note: v.note } : {}) } });
      renderBody();
    } catch (err) { toast(err.message, 'err'); }
  };
}

async function scan(code, fromCamera) {
  let body = { ean: code };
  if (state.complaintMode) {
    if (fromCamera) await closeCamera();
    let name = code;
    try { const l = await api('/api/lookup?ean=' + encodeURIComponent(code)); if (l.found) name = l.variant.name; } catch { /* pokaż sam kod */ }
    const v = await formDialog('Reklamacja', [
      { name: 'note', label: 'Co jest nie tak?', type: 'textarea', required: true, placeholder: 'np. dziura na rękawie, brak metki, uszkodzone pudełko' },
      { name: 'qty', label: 'Ilość sztuk', inputmode: 'numeric', value: '1' },
    ], { okLabel: 'Dodaj reklamację', intro: `<p class="small"><b>${esc(name)}</b></p>`,
      validate: (x) => (x.note.length < 3 ? 'Opisz usterkę' : !(parseInt(x.qty, 10) >= 1) ? 'Podaj ilość' : null) });
    if (!v) return;
    body = { ean: code, damaged: true, note: v.note, qty: parseInt(v.qty, 10) };
  }
  let res;
  try { res = await api(`/api/receipts/${state.receipt.id}/scan`, { body }); } catch (e) {
    if (e.code !== 'unknown_ean') throw e;
    beep(false);
    if (fromCamera) camInfo('✗ Nieznany kod');
    state.lastScanHtml = `<div class="last-scan bad"><b>Nieznany kod ${esc(code)}</b><div class="small">Tego produktu nie ma w bazie – dodaj go jako dostawę (Więcej → Dostawa) albo zgłoś administratorowi.</div></div>`;
    $('#last-scan').innerHTML = state.lastScanHtml;
    return;
  }
  state.receipt = res.receipt;
  const L = res.last;
  const cls = state.complaintMode ? 'bad' : L.scanned > L.expected ? 'warn' : 'ok';
  const msg = state.complaintMode ? 'Dodano do reklamacji' : L.expected === 0 ? 'Tego nie ma w drodze – wejdzie jako nadwyżka'
    : L.scanned > L.expected ? 'Więcej niż w drodze – nadwyżka' : L.scanned === L.expected ? 'Komplet ✓' : `Jeszcze ${L.expected - L.scanned}`;
  state.lastScanHtml = `<div class="last-scan ${cls}"><div class="row"><div class="grow"><b>${esc(L.variant.name)}</b><div class="small">${esc(msg)}</div></div>
    <div class="count">${L.scanned}<span class="small muted"> / ${L.expected}</span></div></div></div>`;
  $('#last-scan').innerHTML = state.lastScanHtml;
  beep(cls !== 'warn');
  if (fromCamera) camInfo(`${L.variant.name}: ${L.scanned} / ${L.expected}`);
  renderBody();
}

async function confirmReceipt() {
  const r = state.receipt;
  if (!r.lines.length) { toast('Nic nie zeskanowano', 'err'); return; }
  const damaged = r.lines.filter((l) => l.damaged).reduce((s, l) => s + l.qty, 0);
  const ok = await confirmDialog('Zatwierdzić przyjęcie?', `
    <p>Na magazyn <b>Główny</b>: <b>${r.total_qty - damaged} szt.</b><br>Na magazyn <b>Reklamacje</b>: <b>${damaged} szt.</b></p>
    ${r.missing_qty ? `<p style="color:var(--warn)">Brakuje ${r.missing_qty} szt. – zostaną w „W drodze”.</p>` : ''}
    ${r.surplus_qty ? `<p style="color:var(--warn)">Nadwyżka ${r.surplus_qty} szt. – wejdzie z ostatnią znaną ceną zakupu.</p>` : ''}
    <p class="small muted">Po zatwierdzeniu w Fakturowni powstanie dokument MM. Tego nie da się cofnąć z aplikacji.</p>`, 'Zatwierdź');
  if (!ok) return;
  try {
    const res = await api(`/api/receipts/${r.id}/confirm`, { method: 'POST', timeout: 60000 });
    state.lastScanHtml = ''; state.complaintMode = false;
    if (res.sync_status === 'ok') toast(`Przyjęto ✓ ${[res.mm_main_number, res.mm_returns_number].filter(Boolean).join(', ')}`, 'ok');
    else if (res.sync_status === 'wylaczone') toast('Przyjęto (tryb testowy – bez Fakturowni)', 'ok');
    else toast('Przyjęto w aplikacji. Fakturownia: ' + (res.sync_error || 'wyśle się później'), 'err');
    nav.render();
  } catch (e) { toast(e.message, 'err'); }
}

async function historyHtml() {
  try {
    const list = await api('/api/receipts?limit=10');
    if (!list.length) return '';
    return '<div class="section-title">Ostatnie przyjęcia</div><div class="list">' + list.map((r) => {
      const dmg = r.lines.filter((l) => l.damaged).reduce((s, l) => s + l.qty, 0);
      return `<div class="item"><div class="row"><div class="grow"><div class="name">${r.total_qty} szt.${dmg ? ` <span class="small" style="color:var(--bad)">(${dmg} reklamacji)</span>` : ''}</div>
        <div class="meta">${fmtDate(r.confirmed_at)} · ${esc(r.confirmed_by)}</div>${r.sync_error ? `<div class="small" style="color:var(--bad)">${esc(r.sync_error)}</div>` : ''}</div>
        ${syncTag(r, [r.mm_main_number, r.mm_returns_number].filter(Boolean).join(', ') || 'MM')}</div></div>`;
    }).join('') + '</div>';
  } catch { return ''; }
}
