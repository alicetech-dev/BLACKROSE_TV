// La sala de control del canal: lo que muestran los monitores de la pieza hacker y la tele del cuarto de Joy.
// Lee /api/tv (al aire), /api/cartelera y /api/chat (los proxies de ligero/sala.py hacia el overlay :8822).
// Nada del PC (ni procesos, ni usuario, ni hostname): solo lo que el canal ya muestra al público.
const J = (u) => fetch(u, { cache: 'no-store' }).then((r) => r.json()).catch(() => null);
const hhmm = (n) => String(Math.floor(n / 60) % 24).padStart(2, '0') + ':' + String(n % 60).padStart(2, '0');

export function crearCanal() {
  const E = { tv: null, chat: [], cart: null }, Z = { dormida: () => false, restante: () => 0 };
  const hms = (sg) => { sg = Math.max(0, Math.floor(sg)); return [Math.floor(sg / 3600), Math.floor(sg / 60) % 60, sg % 60].map((n) => String(n).padStart(2, '0')).join(':'); };
  async function refrescar() { const [tv, chat, cart] = await Promise.all([J('/api/tv'), J('/api/chat'), J('/api/cartelera')]); if (tv) E.tv = tv; if (Array.isArray(chat)) E.chat = chat; if (cart) E.cart = cart; }
  refrescar(); setInterval(refrescar, 4000);

  // la noche va de las 22 a las 6: las horas de madrugada cuentan como del día siguiente
  const min = (s) => { const [h, m] = String(s || '0:0').split(':').map(Number); return (h < 12 ? h + 24 : h) * 60 + m; };
  function bloques() {
    const d = new Date(), ahora = (d.getHours() < 12 ? d.getHours() + 24 : d.getHours()) * 60 + d.getMinutes();
    return (E.cart?.bloques || []).map((b) => ({ ...b, i: min(b.ini), f: min(b.ini) + (b.dura || 40), ahora }));
  }
  const recorta = (g, t, w) => { t = String(t || ''); while (t.length > 1 && g.measureText(t).width > w) t = t.slice(0, -2); return t; };
  function partir(g, t, w) {                       // texto en líneas del ancho w
    const out = []; let l = '';
    for (const p of String(t || '').split(/\s+/)) { const n = l ? l + ' ' + p : p; if (g.measureText(n).width > w && l) { out.push(l); l = p; } else l = n; }
    if (l) out.push(l); return out;
  }
  const alAire = () => !!E.tv && E.tv.modo && E.tv.modo !== 'idle';

  // ---- monitor 1: AL AIRE
  function alAireCard(g, w, h, grande = false) {
    const s = grande ? 1.35 : 1, t = performance.now() / 1000, vivo = alAire();
    g.fillStyle = '#05060a'; g.fillRect(0, 0, w, h);
    g.fillStyle = vivo ? (Math.floor(t * 1.4) % 2 ? '#ff2f4f' : '#8a1228') : '#555'; g.beginPath(); g.arc(34 * s, 38 * s, 11 * s, 0, 7); g.fill();
    g.font = `800 ${26 * s}px monospace`; g.fillStyle = '#fff'; g.fillText(vivo ? 'AL AIRE' : 'EN ESPERA', 56 * s, 48 * s);
    g.font = `700 ${18 * s}px monospace`; g.fillStyle = '#ff9ad8'; g.textAlign = 'right'; g.fillText('BLACKROSE TV', w - 22 * s, 46 * s); g.textAlign = 'left';
    g.fillStyle = '#1b1d2e'; g.fillRect(22 * s, 66 * s, w - 44 * s, 2);
    const act = bloques().find((b) => b.ahora >= b.i && b.ahora < b.f);
    const tag = act?.nombre || E.tv?.tag || 'CANAL NOCTURNO', col = act?.color || E.tv?.color || '#39d0ff';
    g.font = `700 ${20 * s}px monospace`; g.fillStyle = col; g.fillText(recorta(g, tag, w - 44 * s), 24 * s, 104 * s);
    g.font = `800 ${34 * s}px monospace`; g.fillStyle = '#fff';
    partir(g, E.tv?.titulo || E.tv?.tema || act?.sub || E.tv?.tag || 'Programación nocturna', w - 48 * s).slice(0, 3).forEach((l, i) => g.fillText(l, 24 * s, (152 + i * 42) * s));
    const d = new Date(); g.font = `800 ${52 * s}px monospace`; g.fillStyle = '#9dffb0'; g.fillText(d.toTimeString().slice(0, 8), 24 * s, h - 28 * s);
    const sig = bloques().filter((b) => b.i > b.ahora).sort((a, b) => a.i - b.i)[0];
    if (sig) { g.font = `600 ${15 * s}px monospace`; g.fillStyle = '#8f8bc4'; g.textAlign = 'right'; g.fillText(recorta(g, `siguiente · ${sig.ini} ${sig.nombre}`, w * 0.55), w - 22 * s, h - 30 * s); g.textAlign = 'left'; }
  }
  // ---- monitor 2: CARTELERA
  function cartelera(g, w, h) {
    g.fillStyle = '#05060a'; g.fillRect(0, 0, w, h);
    g.font = '800 24px monospace'; g.fillStyle = '#39d0ff'; g.fillText('CARTELERA · ' + (E.cart?.noche || 'esta noche'), 22, 40);
    g.fillStyle = '#1b1d2e'; g.fillRect(22, 54, w - 44, 2);
    const bs = bloques(); if (!bs.length) { g.font = '600 20px monospace'; g.fillStyle = '#8f8bc4'; g.fillText('sin cartelera cargada', 22, 100); return; }
    const ahora = bs[0].ahora; let k = bs.findIndex((b) => b.f > ahora); if (k < 0) k = 0;
    bs.slice(Math.max(0, k - 1), Math.max(0, k - 1) + 8).forEach((b, i) => {
      const y = 92 + i * 47, en = ahora >= b.i && ahora < b.f;
      if (en) { g.fillStyle = '#ff4fb822'; g.fillRect(14, y - 30, w - 28, 42); }
      g.font = '700 20px monospace'; g.fillStyle = en ? '#ff9ad8' : '#9dffb0'; g.fillText(b.ini, 22, y);
      g.fillStyle = en ? '#fff' : '#c9c6f0'; g.fillText(recorta(g, b.nombre, w - 190), 104, y);
      if (en) { g.fillStyle = '#ff2f4f'; g.font = '700 14px monospace'; g.textAlign = 'right'; g.fillText('● AHORA', w - 24, y); g.textAlign = 'left'; }
    });
  }
  // ---- monitor de la cámara de circuito cerrado: Alice duerme y cuándo despierta
  function suenoCard(g, w, h) {
    const t = performance.now() / 1000;
    g.fillStyle = '#031006'; g.fillRect(0, 0, w, h);
    g.fillStyle = Math.floor(t * 1.2) % 2 ? '#ff2f4f' : '#8a1228'; g.beginPath(); g.arc(34, 38, 11, 0, 7); g.fill();
    g.font = '800 24px monospace'; g.fillStyle = '#9dffb0'; g.fillText('REC · CAM 02 · DORMITORIO', 56, 46);
    g.fillStyle = '#12301a'; g.fillRect(22, 62, w - 44, 2);
    g.font = '800 44px monospace'; g.fillStyle = '#fff'; g.textAlign = 'center'; g.fillText('ALICE DUERME', w / 2, 170);
    g.font = '700 22px monospace'; g.fillStyle = '#9dffb0'; g.fillText('despierta en', w / 2, 240);
    g.font = '800 76px monospace'; g.fillStyle = '#ff9ad8'; g.fillText(hms(Z.restante()), w / 2, 330);
    g.font = '600 18px monospace'; g.fillStyle = '#4b9a5a'; g.fillText('shhh · no hacer ruido ♥', w / 2, 400); g.textAlign = 'left';
    for (let y = 0; y < h; y += 4) { g.fillStyle = '#00000030'; g.fillRect(0, y, w, 1); }
  }
  // ---- monitor 3: CHAT
  function chat(g, w, h) {
    g.fillStyle = '#05060a'; g.fillRect(0, 0, w, h);
    g.font = '800 24px monospace'; g.fillStyle = '#c9a2ff'; g.fillText('CHAT · en vivo', 22, 40);
    g.fillStyle = '#1b1d2e'; g.fillRect(22, 54, w - 44, 2);
    const ult = E.chat.slice(-7);
    if (!ult.length) { g.font = '600 20px monospace'; g.fillStyle = '#8f8bc4'; g.fillText('escribe en el chat y te leemos ♥', 22, 100); return; }
    let y = 90;
    for (const m of ult) {
      g.font = '700 18px monospace'; g.fillStyle = m.color || '#ff9ad8'; const a = recorta(g, m.autor, 200); g.fillText(a, 22, y);
      const x = 30 + g.measureText(a).width; g.font = '600 18px monospace'; g.fillStyle = '#e8e6ff'; g.fillText(recorta(g, ': ' + m.texto, w - x - 20), x - 8, y);
      y += 48;
    }
  }
  return {
    pintarMonitores(gs, w, h) { alAireCard(gs[0], w, h); if (Z.dormida()) suenoCard(gs[1], w, h); else cartelera(gs[1], w, h); chat(gs[2], w, h); },
    pintarTele(g, w, h) {
      alAireCard(g, w, h, true);
      if (Z.dormida()) { g.fillStyle = '#031006e8'; g.fillRect(0, h - 78, w, 78); g.font = '800 34px monospace'; g.fillStyle = '#9dffb0'; g.textAlign = 'center'; g.fillText('😴 ALICE DUERME · despierta en ' + hms(Z.restante()), w / 2, h - 28); g.textAlign = 'left'; }
    },
    setSueno(dormida, restante) { Z.dormida = dormida; Z.restante = restante; },
    get alAire() { return alAire(); },
  };
}
