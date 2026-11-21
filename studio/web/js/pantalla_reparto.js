// Pantalla MI REPARTO: arrastrar un .vrm, ver el informe (errores/avisos/licencia), vista 3D, miniatura y ponerlo en el set.
import { crearVistaAvatar } from './vista_avatar.js';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
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

  const listo = recargar();
  return { recargar, puestos, activar: (arg) => { puestos(); if (arg) listo.then(() => seleccionar(arg)); } };
}
