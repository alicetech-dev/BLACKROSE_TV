// Pantalla MI REPARTO: arrastrar un .vrm, ver el informe (errores/avisos/licencia), vista 3D, miniatura y ponerlo en el set.
import { crearVistaAvatar } from './vista_avatar.js';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ROLES = ['', 'conductora', 'panelista', 'reportera', 'invitada', 'fondo'];
const IDIOMAS = ['', 'es', 'en', 'ja', 'pt', 'fr', 'de', 'it'];
const DESLIZ = [['temperatura', 0.05, 1.5, 0.05], ['velocidad', 0.5, 2, 0.05], ['tono', 0.5, 2, 0.01]];
const leer = (o, ruta) => ruta.split('.').reduce((x, k) => x?.[k], o);
const parche = (ruta, v) => ruta.split('.').reduceRight((acc, k) => ({ [k]: acc }), v);
const mb = (b) => (b / 1048576).toFixed(1).replace('.', ',') + ' MB';

export function montarReparto(raiz, { t, escena, enviarEscena, alCambiarLista = () => {} }) {
  raiz.innerHTML = `
  <div class="rep-izq">
    <label class="tarjeta zona" id="zona">
      <input type="file" accept=".vrm" id="archivo" hidden>
      <span class="zona-ic">⇪</span><b>${t('rep.soltar')}</b><small>${t('rep.soltar_ayuda')}</small>
      <div class="barra" id="barra" hidden><i></i></div>
    </label>
    <label class="opcion"><input type="checkbox" id="optimizar" checked> ${t('rep.optimizar')}</label>
    <div class="tarjeta informe" id="informe" hidden></div>
    <div class="tarjetas" id="lista"></div>
  </div>
  <div class="rep-der tarjeta">
    <div class="vista3d" id="vista3d"><span class="vacio" id="vacio">${t('rep.elige')}</span></div>
    <div id="detalle" hidden>
      <h3 id="d_nombre"></h3><div class="chips" id="d_chips"></div>
      <div class="fila acciones">
        <button class="boton suave" id="d_foto">📸 ${t('rep.foto')}</button>
        <button class="boton peligro" id="d_borrar">🗑 ${t('rep.borrar')}</button>
      </div>
      <label>${t('rep.poner_en')}</label>
      <div class="fila"><select id="d_puesto"></select><button class="boton" id="d_poner">${t('rep.poner')}</button></div>
      <small class="ayuda">${t('rep.girar')}</small>
      <div class="ficha" id="ficha">
        <div class="cabeza"><h2>${t('fic.titulo')}</h2><span class="guardado" id="f_estado"></span></div>
        <div class="fila">
          <div><label>${t('fic.rol')}</label><select data-p="rol">${ROLES.map((r) => `<option value="${r}">${t('rol.' + (r || 'ninguno'))}</option>`).join('')}</select></div>
          <div><label>${t('fic.idioma')}</label><select data-p="idioma">${IDIOMAS.map((i) => `<option value="${i}">${t('idioma.' + (i || 'canal'))}</option>`).join('')}</select></div>
        </div>
        <label>${t('fic.voice')}</label><input type="text" data-p="voz.voice" maxlength="120" spellcheck="false" placeholder="${esc(t('fic.voice_ph'))}">
        ${DESLIZ.map(([k, lo, hi, paso]) => `<div class="desliz"><label>${t('fic.' + k)}</label><input type="range" min="${lo}" max="${hi}" step="${paso}" data-p="voz.${k}" data-num="1"><output data-ver="voz.${k}"></output></div>`).join('')}
        <div class="prueba-voz">
          <input type="text" id="f_frase" maxlength="300" placeholder="${esc(t('fic.frase_ph'))}">
          <button class="boton" id="f_probar">▶ ${t('fic.probar')}</button>
        </div>
        <span class="resultado" id="f_voz"></span>
        <audio id="f_audio" hidden></audio>
        <label>${t('fic.personalidad')}</label><textarea data-p="personalidad" rows="4" maxlength="4000" placeholder="${esc(t('fic.personalidad_ph'))}"></textarea>
        <label>${t('fic.muletillas')}</label><textarea data-p="muletillas" data-lista="1" rows="3" placeholder="${esc(t('fic.muletillas_ph'))}"></textarea>
      </div>
    </div>
  </div>`;
  const $ = (s) => raiz.querySelector(s);
  const vista = crearVistaAvatar($('#vista3d'));
  let lista = [], sel = null;

  const chips = (f) => {
    const i = f.informe, L = i.licencia || {}, c = [`<span class="chip">VRM ${esc(i.version)}</span>`];
    c.push(`<span class="chip">${(i.stats.triangulos / 1000).toFixed(0)} mil △</span>`, `<span class="chip">${mb(f.optimizado?.bytes_ahora ?? i.stats.bytes)}</span>`);
    if (f.optimizado) c.push(`<span class="chip ok">${t('rep.optimizado')} −${mb(f.optimizado.bytes_antes - f.optimizado.bytes_ahora)}</span>`);
    if (/onlyauthor/i.test(L.uso_avatar)) c.push(`<span class="chip aviso">${t('lic.solo_autora')}</span>`);
    if (!L.comercial) c.push(`<span class="chip aviso">${t('lic.no_comercial')}</span>`);
    if (i.visemas?.length < 5) c.push(`<span class="chip aviso">${t('rep.boca_limitada')}</span>`);
    return c.join('');
  };

  function pintarLista() {
    $('#lista').innerHTML = lista.length ? lista.map((f) => `
      <button class="tarjeta avatar ${f.id === sel?.id ? 'activo' : ''}" data-id="${esc(f.id)}">
        ${f.miniatura ? `<img src="${esc(f.miniatura)}?v=${Date.now() % 1e6}" alt="">` : '<span class="sin-mini">◕‿◕</span>'}
        <b>${esc(f.nombre)}</b><small>VRM ${esc(f.informe.version)} · ${(f.informe.stats.triangulos / 1000).toFixed(0)} mil △</small>
      </button>`).join('') : `<p class="ayuda">${t('rep.vacio')}</p>`;
  }

  function pintarInforme(f, errores) {
    const caja = $('#informe'); caja.hidden = false;
    if (errores) {
      caja.className = 'tarjeta informe mal';
      caja.innerHTML = `<h2>${t('rep.no_se_pudo')}</h2><ul>${errores.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>`;
      return;
    }
    const av = f.informe.avisos;
    caja.className = 'tarjeta informe ' + (av.length ? 'aviso' : 'ok');
    caja.innerHTML = `<h2>✓ ${esc(f.nombre)} ${t('rep.importado')}</h2>` +
      (av.length ? `<ul>${av.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>` : `<p>${t('rep.sin_avisos')}</p>`);
  }

  function puestos() {
    const e = escena(); const POS = (p) => t('pos.' + p);
    $('#d_puesto').innerHTML = (e.reparto || []).map((p, i) => `<option value="${i}">${esc(p.nombre || p.id)} · ${esc(POS(p.pos))}${p.vrm ? ' ●' : ''}</option>`).join('');
  }

  async function seleccionar(id) {
    sel = lista.find((f) => f.id === id) || null; pintarLista();
    $('#detalle').hidden = !sel; $('#vacio').hidden = !!sel;
    if (!sel) { await vista.mostrar(null); return; }
    $('#d_nombre').textContent = sel.nombre; $('#d_chips').innerHTML = chips(sel); puestos();
    cargarFicha(sel.id);
    const ok = await vista.mostrar(sel.vrm);
    if (ok && !sel.miniatura) await guardarFoto();               // sin miniatura propia: se saca sola
  }

  async function guardarFoto() {
    if (!sel) return;
    const blob = await vista.foto();
    const r = await fetch(`/api/reparto/${sel.id}/miniatura`, { method: 'POST', headers: { 'Content-Type': 'image/png' }, body: blob });
    if (r.ok) { const f = await r.json(); Object.assign(sel, f); lista = lista.map((x) => (x.id === f.id ? sel : x)); pintarLista(); }
  }

  async function recargar(idSel) {
    lista = await (await fetch('/api/reparto')).json(); pintarLista(); alCambiarLista(lista);
    if (idSel !== undefined) await seleccionar(idSel);
  }

  function subir(archivo) {
    if (!archivo) return;
    if (!/\.vrm$/i.test(archivo.name)) { pintarInforme(null, [t('rep.solo_vrm')]); return; }
    const fd = new FormData(); fd.append('vrm', archivo); fd.append('optimizar', $('#optimizar').checked ? '1' : '0');
    const x = new XMLHttpRequest(), barra = $('#barra');
    barra.hidden = false; barra.firstElementChild.style.width = '0%'; $('#zona').classList.add('subiendo');
    x.upload.onprogress = (e) => { if (e.lengthComputable) barra.firstElementChild.style.width = `${(e.loaded / e.total) * 100}%`; };
    x.onload = async () => {
      barra.hidden = true; $('#zona').classList.remove('subiendo');
      let d = {}; try { d = JSON.parse(x.responseText); } catch (_) {}
      if (x.status === 201) { pintarInforme(d); await recargar(d.id); } else pintarInforme(null, d.errores || [`HTTP ${x.status}`]);
    };
    x.onerror = () => { barra.hidden = true; $('#zona').classList.remove('subiendo'); pintarInforme(null, [t('desconectado')]); };
    x.open('POST', '/api/reparto'); x.send(fd);
  }

  // ── eventos ──
  const zona = $('#zona');
  $('#archivo').addEventListener('change', (e) => { subir(e.target.files[0]); e.target.value = ''; });
  for (const ev of ['dragenter', 'dragover']) zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add('encima'); });
  for (const ev of ['dragleave', 'drop']) zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove('encima'); });
  zona.addEventListener('drop', (e) => subir(e.dataTransfer.files[0]));
  $('#lista').addEventListener('click', (e) => { const b = e.target.closest('.avatar'); if (b) seleccionar(b.dataset.id); });
  $('#d_foto').addEventListener('click', guardarFoto);
  $('#d_borrar').addEventListener('click', async () => {
    if (!sel) return;
    const b = $('#d_borrar');
    if (b.dataset.confirma !== '1') { b.dataset.confirma = '1'; b.textContent = t('rep.confirmar_borrar'); setTimeout(() => { b.dataset.confirma = ''; b.textContent = '🗑 ' + t('rep.borrar'); }, 3000); return; }
    b.dataset.confirma = ''; b.textContent = '🗑 ' + t('rep.borrar');
    await fetch(`/api/reparto/${sel.id}`, { method: 'DELETE' }); await recargar(null);
  });
  $('#d_poner').addEventListener('click', async () => {
    if (!sel) return;
    const rep = structuredClone(escena().reparto || []), i = +$('#d_puesto').value;
    if (!rep[i]) return;
    rep[i].vrm = sel.vrm; if (!rep[i].nombre) rep[i].nombre = sel.nombre;
    await enviarEscena({ reparto: rep }); puestos();
  });

  // ── ficha de voz y personalidad (guardado automático) ──
  let perfil = null, fPend = {}, fReloj = null, fId = null;
  const fEstado = (clase, txt) => { const e = $('#f_estado'); e.className = 'guardado ' + clase; e.textContent = txt; };
  const verDesliz = () => { for (const o of raiz.querySelectorAll('[data-ver]')) o.textContent = (+leer(perfil, o.dataset.ver)).toFixed(2); };
  function pintarFicha() {
    for (const el of raiz.querySelectorAll('#ficha [data-p]')) {
      if (document.activeElement === el) continue;
      const v = leer(perfil, el.dataset.p);
      el.value = el.dataset.lista ? (v || []).join('\n') : (v ?? '');
    }
    verDesliz();
  }
  async function cargarFicha(id) {
    fId = id; perfil = null; fEstado('', ''); $('#f_voz').textContent = '';
    const r = await fetch(`/api/reparto/${id}/perfil`);
    if (r.ok && fId === id) { perfil = await r.json(); pintarFicha(); }
  }
  const unir = (a, b) => { for (const [k, v] of Object.entries(b)) a[k] = (v && typeof v === 'object' && !Array.isArray(v) && a[k] && typeof a[k] === 'object') ? unir(a[k], v) : v; return a; };
  async function guardarFicha() {
    const p = fPend, id = fId; fPend = {}; fReloj = null;
    if (!Object.keys(p).length || !id) return;
    fEstado('guardando', t('guardando'));
    try {
      const r = await fetch(`/api/reparto/${id}/perfil`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) });
      const d = await r.json();
      if (!r.ok) { fEstado('mal', '⚠ ' + (d.error || r.status)); return; }
      if (id === fId) { perfil = d; pintarFicha(); if (!fReloj) fEstado('ok', '✓ ' + t('guardado')); }
    } catch (_) { fEstado('mal', '⚠ ' + t('desconectado')); }
  }
  $('#ficha').addEventListener('input', (e) => {
    const el = e.target.closest('[data-p]'); if (!el || !perfil) return;
    let v = el.value;
    if (el.dataset.num) v = +v;
    if (el.dataset.lista) v = v.split('\n').map((x) => x.trim()).filter(Boolean);
    unir(perfil, parche(el.dataset.p, v)); verDesliz();
    unir(fPend, parche(el.dataset.p, v)); clearTimeout(fReloj); fEstado('guardando', t('sin_guardar'));
    fReloj = setTimeout(guardarFicha, el.tagName === 'SELECT' ? 0 : 700);
  });
  $('#ficha').addEventListener('focusout', () => { if (fReloj) { clearTimeout(fReloj); guardarFicha(); } });

  // ── ▶ probar voz: el servidor sintetiza con XTTS la frase que escribió ella ──
  $('#f_probar').addEventListener('click', async () => {
    const caja = $('#f_voz'), b = $('#f_probar'), frase = $('#f_frase').value.trim();
    if (!sel || !perfil) return;
    if (!frase) { caja.className = 'resultado aviso'; caja.textContent = t('voz.sin_frase'); $('#f_frase').focus(); return; }
    if (fReloj) { clearTimeout(fReloj); await guardarFicha(); }
    b.disabled = true; caja.className = 'resultado'; caja.textContent = t('voz.generando');
    const lento = setTimeout(() => { caja.className = 'resultado aviso'; caja.textContent = t('voz.arrancando'); }, 2500);
    try {
      const r = await fetch(`/api/reparto/${sel.id}/probar_voz`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frase, voz: perfil.voz }) });
      clearTimeout(lento);
      if (r.ok) {
        const a = $('#f_audio'); if (a.src) URL.revokeObjectURL(a.src);
        a.src = URL.createObjectURL(await r.blob());
        caja.className = 'resultado ok'; caja.textContent = '♪ ' + t('voz.sonando');
        try { await a.play(); } catch (_) { caja.textContent = t('voz.sin_permiso_audio'); }
      } else {
        let d = {}; try { d = await r.json(); } catch (_) {}
        caja.className = 'resultado mal'; caja.textContent = t('voz.err.' + (d.codigo || 'rechazo')) + (d.error && d.codigo !== 'no_responde' ? ` · ${d.error}` : '');
      }
    } catch (_) { clearTimeout(lento); caja.className = 'resultado mal'; caja.textContent = t('desconectado'); }
    b.disabled = false;
  });
  $('#f_frase').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#f_probar').click(); });

  const listo = recargar();
  return { recargar, puestos, activar: (arg) => { puestos(); if (arg) listo.then(() => seleccionar(arg)); } };
}
