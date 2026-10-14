// Drobne narzędzia interfejsu: formatowanie, ikony, dźwięk, komunikaty i okna dialogowe.
export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const num = (v) => { const n = parseFloat(String(v ?? '').replace(/\s/g, '').replace(',', '.')); return Number.isFinite(n) ? n : NaN; };
export const round2 = (n) => Math.round((n + Number.EPSILON) * 100) / 100;
export const zl = (n) => (Number.isFinite(+n) ? (+n).toLocaleString('pl-PL', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '–') + ' zł';
export const gross = (net, tax) => { const t = num(tax); return round2(num(net) * (1 + (Number.isFinite(t) ? t : 0) / 100)); };
export const fmtDate = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit' }) + ' ' + d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
};
export const VAT_RATES = ['23', '8', '5', '0', 'zw'];
export const vatOptions = VAT_RATES.map((r) => ({ value: r, label: r === 'zw' ? 'zwolniony' : r + '%' }));

const svg = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
export const ICON = {
  cart: svg('<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.7 12.4a2 2 0 0 0 2 1.6h7.6a2 2 0 0 0 2-1.5L21 8H6"/>'),
  truck: svg('<path d="M3 6h11v10H3zM14 9h4l3 3v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>'),
  box: svg('<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>'),
  tag: svg('<path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.5"/>'),
  more: svg('<path d="M4 6h16M4 12h16M4 18h16"/>'),
  cam: svg('<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 8v8M10 8v8M13 8v8M17 8v8"/>'),
  file: svg('<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>'),
  alert: svg('<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'),
  list: svg('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
  gear: svg('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>'),
  out: svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>'),
};

let audioCtx;
export function beep(ok = true) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(); const g = audioCtx.createGain();
    o.frequency.value = ok ? 1250 : 330; o.type = ok ? 'sine' : 'square';
    g.gain.value = 0.08; o.connect(g); g.connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + (ok ? 0.08 : 0.35));
  } catch { /* brak dźwięku */ }
  if (navigator.vibrate) navigator.vibrate(ok ? 40 : [80, 60, 80]);
}

let toastTimer;
export function toast(msg, kind = '') {
  const t = $('#toast');
  t.textContent = msg; t.className = kind; t.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), kind === 'err' ? 5000 : 2500);
}

export function openDialog(html) {
  const dlg = $('#dlg');
  dlg.onclick = null; dlg.oncancel = null;
  dlg.innerHTML = html;
  if (!dlg.open) dlg.showModal();
  return dlg;
}
export function closeDialog() { const d = $('#dlg'); if (d.open) d.close(); }

export function confirmDialog(title, bodyHtml, okLabel = 'OK', okClass = 'primary') {
  return new Promise((resolve) => {
    const dlg = openDialog(`<div class="dlg-head">${esc(title)}</div><div class="dlg-body">${bodyHtml}</div>
      <div class="dlg-foot"><button class="btn" data-x="no">Anuluj</button><button class="btn ${okClass}" data-x="yes">${esc(okLabel)}</button></div>`);
    dlg.onclick = (e) => { const x = e.target.closest('[data-x]'); if (!x) return; dlg.onclick = null; closeDialog(); resolve(x.dataset.x === 'yes'); };
    dlg.oncancel = () => resolve(false);
  });
}

/** Formularz w oknie. fields: [{name,label,type,value,options,required,inputmode,placeholder,list,listValues,hint}] */
export function formDialog(title, fields, { okLabel = 'Zapisz', intro = '', validate, onInput } = {}) {
  return new Promise((resolve) => {
    const inputs = fields.map((f) => {
      const id = 'f_' + f.name;
      const common = `id="${id}" name="${f.name}" ${f.required ? 'required' : ''} ${f.inputmode ? `inputmode="${f.inputmode}"` : ''} placeholder="${esc(f.placeholder || '')}"`;
      let ctl;
      if (f.type === 'select') ctl = `<select ${common}>${f.options.map((o) => `<option value="${esc(o.value ?? o)}" ${String(o.value ?? o) === String(f.value) ? 'selected' : ''}>${esc(o.label ?? o)}</option>`).join('')}</select>`;
      else if (f.type === 'textarea') ctl = `<textarea ${common}>${esc(f.value || '')}</textarea>`;
      else if (f.type === 'checkbox') return `<label class="toggle"><input type="checkbox" ${common} ${f.value ? 'checked' : ''}> ${esc(f.label)}</label>`;
      else ctl = `<input type="${f.type || 'text'}" ${common} value="${esc(f.value ?? '')}" ${f.list ? `list="${f.list}"` : ''} autocomplete="off">`;
      return `<label class="field"><span>${esc(f.label)}</span>${ctl}${f.hint ? `<div class="small muted" id="${id}_hint">${f.hint}</div>` : ''}</label>`;
    }).join('');
    const lists = fields.filter((f) => f.list && f.listValues).map((f) => `<datalist id="${f.list}">${f.listValues.map((v) => `<option value="${esc(v)}">`).join('')}</datalist>`).join('');
    const dlg = openDialog(`<form method="dialog" id="dlg-form"><div class="dlg-head">${esc(title)}</div>
      <div class="dlg-body">${intro}${inputs}${lists}<p class="small" id="dlg-err" style="color:var(--bad)"></p></div>
      <div class="dlg-foot"><button type="button" class="btn" id="dlg-cancel">Anuluj</button><button class="btn primary" type="submit">${esc(okLabel)}</button></div></form>`);
    const form = $('#dlg-form', dlg);
    const read = () => { const o = {}; for (const f of fields) { const el = form.elements[f.name]; o[f.name] = f.type === 'checkbox' ? el.checked : el.value.trim(); } return o; };
    if (onInput) { form.addEventListener('input', () => onInput(read(), dlg)); onInput(read(), dlg); }
    const first = form.querySelector('input:not([type=checkbox]),select,textarea');
    setTimeout(() => first && first.focus(), 60);
    $('#dlg-cancel', dlg).onclick = () => { closeDialog(); resolve(null); };
    dlg.oncancel = () => resolve(null);
    form.onsubmit = (e) => {
      e.preventDefault();
      const vals = read();
      const err = validate && validate(vals);
      if (err) { $('#dlg-err', dlg).textContent = err; return; }
      closeDialog(); resolve(vals);
    };
  });
}

export const grossHint = (x, dlg) => {
  const h = $('#f_price_net_hint', dlg);
  if (h) h.textContent = Number.isFinite(num(x.price_net)) ? 'Brutto: ' + zl(gross(x.price_net, x.tax)) : '';
};
