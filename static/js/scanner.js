// Skanowanie: aparat w telefonie, czytnik Bluetooth/USB (działa jak klawiatura) albo wpisanie kodu.
import { state } from './state.js';
import { $, ICON, beep, esc, toast } from './ui.js';

const cleanEan = (s) => String(s || '').replace(/[^0-9A-Za-z]/g, '');
let handler = null;
let qr = null;
let lastCam = { code: '', at: 0 };

/** Ustawia, co robi skan na bieżącym ekranie (null = skanowanie wyłączone). */
export function setScanHandler(fn) { handler = fn; }

export async function handleScan(code, fromCamera = false) {
  code = cleanEan(code);
  if (code.length < 4) return;
  if (!handler) { toast('Na tym ekranie nie można skanować'); return; }
  if (!state.online) { beep(false); toast('Brak internetu – skan nie został zapisany', 'err'); return; }
  try { await handler(code, fromCamera); } catch (e) { beep(false); if (fromCamera) camInfo('✗ ' + e.message); toast(e.message || String(e), 'err'); }
}

export function camInfo(text) { $('#cam-last').textContent = text; }

export async function openCamera() {
  if (typeof Html5Qrcode === 'undefined') { toast('Brak biblioteki skanera', 'err'); return; }
  $('#camera').classList.remove('hidden');
  camInfo('');
  const F = Html5QrcodeSupportedFormats;
  try {
    qr = qr || new Html5Qrcode('reader', {
      verbose: false,
      formatsToSupport: [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39, F.ITF],
      experimentalFeatures: { useBarCodeDetectorIfSupported: true },
    });
    await qr.start({ facingMode: 'environment' },
      { fps: 12, qrbox: (w, h) => ({ width: Math.min(w * 0.85, 360), height: Math.min(h * 0.35, 160) }), aspectRatio: 1.333 },
      (text) => {
        const code = cleanEan(text); const t = Date.now();
        if (code === lastCam.code && t - lastCam.at < 2000) return; // ten sam kod – nie dubluj
        lastCam = { code, at: t };
        handleScan(code, true);
      }, () => {});
  } catch {
    closeCamera();
    toast(location.protocol === 'https:' || location.hostname === 'localhost'
      ? 'Nie udało się włączyć aparatu – sprawdź uprawnienia' : 'Aparat działa tylko przez https://', 'err');
  }
}

export async function closeCamera() {
  $('#camera').classList.add('hidden');
  if (qr) { try { if (qr.isScanning) await qr.stop(); } catch { /* już zatrzymany */ } }
}

// czytnik Bluetooth/USB szybko „wpisuje” cyfry i Enter
const wedge = { buf: '', first: 0, last: 0 };
document.addEventListener('keydown', (e) => {
  if ($('#dlg').open) return;
  const t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
  const now = Date.now();
  if (now - wedge.last > 120) { wedge.buf = ''; wedge.first = now; }
  wedge.last = now;
  if (e.key === 'Enter') {
    if (wedge.buf.length >= 6 && now - wedge.first < 1500) { e.preventDefault(); handleScan(wedge.buf); }
    wedge.buf = '';
  } else if (e.key.length === 1) wedge.buf += e.key;
});

export function scanBar(placeholder = 'Zeskanuj lub wpisz EAN') {
  return `<form class="scanbar" id="scan-form"><input id="scan-input" type="text" inputmode="numeric" placeholder="${esc(placeholder)}" autocomplete="off" enterkeyhint="go">
    <button type="button" class="btn primary cam" id="cam-btn" aria-label="Skanuj aparatem">${ICON.cam}</button></form>`;
}

export function bindScanBar() {
  const f = $('#scan-form'); if (!f) return;
  f.onsubmit = (e) => { e.preventDefault(); const i = $('#scan-input'); const v = i.value; i.value = ''; handleScan(v); };
  $('#cam-btn').onclick = openCamera;
}

$('#cam-close').onclick = closeCamera;
