// Pantalla ESTACIÓN: los prompts de la estación (vacíos de fábrica) y la configuración de la IA. Guardado automático.
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const FORMATOS = ['noticias', 'deportes', 'panel', 'entrevistas', 'late_show', 'documental'];
const MAX = 20000;

/** Lee una ruta «a.b.c» de un objeto. */
const leer = (o, ruta) => ruta.split('.').reduce((x, k) => x?.[k], o);
/** {a:{b:v}} a partir de «a.b» y v. */
const parche = (ruta, v) => ruta.split('.').reduceRight((acc, k) => ({ [k]: acc }), v);

export function montarEstacion(raiz, { t }) {
  const area = (ruta, ayuda, filas = 6) => `
    <div class="campo-largo">
      <textarea data-ruta="${ruta}" rows="${filas}" maxlength="${MAX}" placeholder="${esc(t(ayuda))}" spellcheck="true"></textarea>
      <small class="contador" data-cuenta="${ruta}"></small>
    </div>`;
  raiz.innerHTML = `
  <div class="est-izq">
    <div class="tarjeta">
      <div class="cabeza"><h2>${t('est.titulo')}</h2><span class="guardado" id="g_estado"></span></div>
      <p class="ayuda">${t('est.intro')}</p>
      <label>${t('est.prompt_sistema')}</label>${area('estacion.prompt_sistema', 'est.ph_sistema', 7)}
      <label>${t('est.directriz')}</label>${area('estacion.directriz', 'est.ph_directriz', 4)}
    </div>
    <div class="tarjeta">
      <h2>${t('est.formatos')}</h2>
      <div class="pestanas" id="formatos">${FORMATOS.map((f, i) => `<button data-f="${f}" class="${i ? '' : 'activo'}">${t('set.' + f)}<i></i></button>`).join('')}</div>
      ${FORMATOS.map((f, i) => `<div data-panel="${f}" ${i ? 'hidden' : ''}>${area(`estacion.formatos.${f}.prompt`, 'est.ph_formato', 7)}</div>`).join('')}
    </div>
    <div class="tarjeta dos">
      <div><label>${t('est.apertura')}</label>${area('estacion.apertura', 'est.ph_apertura', 4)}</div>
      <div><label>${t('est.cierre')}</label>${area('estacion.cierre', 'est.ph_cierre', 4)}</div>
    </div>
    <details class="tarjeta fija">
      <summary>🔒 ${t('est.instruccion')}</summary>
      <p class="ayuda">${t('est.instruccion_ayuda')}</p>
      <pre id="instruccion"></pre>
    </details>
  </div>
  <div class="est-der">
    <div class="tarjeta">
      <h2>${t('ia.titulo')}</h2>
      <div class="alterna" id="ia_modo">${['local', 'online', 'manual'].map((m) => `<button data-v="${m}">${t('ia.modo.' + m)}</button>`).join('')}</div>
      <p class="ayuda" id="ia_modo_ayuda"></p>
      <label class="opcion"><input type="checkbox" data-ruta="ia.secuencial"> ${t('ia.secuencial')}</label>
      <small class="ayuda">${t('ia.secuencial_ayuda')}</small>
    </div>
    <div class="tarjeta" id="caja_llm">
      <h2>🧠 ${t('ia.llm')}</h2>
      <label>${t('ia.llm_url')}</label><input type="text" data-ruta="ia.local.llm_url" spellcheck="false">
      <label>${t('ia.modelo')}</label><input type="text" data-ruta="ia.local.modelo" spellcheck="false" placeholder="${esc(t('ia.modelo_ph'))}">
      <div class="fila prueba"><button class="boton suave" data-probar="llm">${t('ia.probar')}</button><span class="resultado" id="r_llm"></span></div>
    </div>
    <div class="tarjeta">
      <h2>🎙 ${t('ia.voz')}</h2>
      <label>${t('ia.motor')}</label><select data-ruta="ia.voz.motor"><option value="xtts">XTTS</option></select>
      <label>${t('ia.voz_url')}</label><input type="text" data-ruta="ia.voz.url" spellcheck="false">
      <label>${t('ia.voz_salud')}</label><input type="text" data-ruta="ia.voz.url_salud" spellcheck="false" placeholder="${esc(t('ia.voz_salud_ph'))}">
      <div class="fila prueba"><button class="boton suave" data-probar="voz">${t('ia.probar')}</button><span class="resultado" id="r_voz"></span></div>
    </div>
    <div class="tarjeta">
      <h2>⚙ ${t('ia.ganchos')}</h2>
      <p class="ayuda">${t('ia.ganchos_ayuda')}</p>
      <label>${t('ia.antes_de_guion')}</label><input type="text" data-ruta="ia.local.antes_de_guion" spellcheck="false" placeholder="${esc(t('ia.gancho_ph'))}">
      <label>${t('ia.antes_de_voz')}</label><input type="text" data-ruta="ia.local.antes_de_voz" spellcheck="false" placeholder="${esc(t('ia.gancho_ph'))}">
    </div>
  </div>`;

  const $ = (s) => raiz.querySelector(s);
  let datos = null;
  const estado = $('#g_estado');
  const marcar = (clase, texto) => { estado.className = 'guardado ' + clase; estado.textContent = texto; };

  const contar = (el) => {
    const c = raiz.querySelector(`[data-cuenta="${el.dataset.ruta}"]`);
    if (c) { c.textContent = `${el.value.length.toLocaleString()} / ${MAX.toLocaleString()}`; c.classList.toggle('lleno', el.value.length > MAX * 0.9); }
  };
  const pintarFormatos = () => {
    for (const b of $('#formatos').children) b.classList.toggle('con', !!leer(datos, `estacion.formatos.${b.dataset.f}.prompt`));
  };
  const pintarModo = () => {
    const m = datos.ia.modo;
    for (const b of $('#ia_modo').children) b.classList.toggle('activo', b.dataset.v === m);
    $('#ia_modo_ayuda').textContent = t('ia.modo_ayuda.' + m);
    $('#caja_llm').classList.toggle('apagada', m !== 'local');
  };
  function pintar() {
    for (const el of raiz.querySelectorAll('[data-ruta]')) {
      if (document.activeElement === el) continue;
      const v = leer(datos, el.dataset.ruta);
      if (el.type === 'checkbox') el.checked = !!v; else el.value = v ?? '';
      if (el.tagName === 'TEXTAREA') contar(el);
    }
    pintarFormatos(); pintarModo();
  }

  // ── guardado automático: se juntan los cambios y se mandan tras una pausa ──
  let pendiente = {}, reloj = null, enVuelo = Promise.resolve();
  const unir = (a, b) => { for (const [k, v] of Object.entries(b)) a[k] = (v && typeof v === 'object' && !Array.isArray(v) && a[k] && typeof a[k] === 'object') ? unir(a[k], v) : v; return a; };
  async function enviar() {
    const p = pendiente; pendiente = {}; reloj = null;
    if (!Object.keys(p).length) return;
    marcar('guardando', t('guardando'));
    enVuelo = enVuelo.then(async () => {
      try {
        const r = await fetch('/api/proyecto', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p) });
        const d = await r.json();
        if (!r.ok) { marcar('mal', '⚠ ' + (d.error || r.status)); return; }
        datos = d; pintar();
        if (!reloj) marcar('ok', '✓ ' + t('guardado'));
      } catch (_) { marcar('mal', '⚠ ' + t('desconectado')); }
    });
  }
  const cambiar = (ruta, v, ya = false) => {
    unir(pendiente, parche(ruta, v)); clearTimeout(reloj); marcar('guardando', t('sin_guardar'));
    reloj = setTimeout(enviar, ya ? 0 : 700);
  };

  raiz.addEventListener('input', (e) => {
    const el = e.target.closest('[data-ruta]'); if (!el) return;
    if (el.tagName === 'TEXTAREA') contar(el);
    const v = el.type === 'checkbox' ? el.checked : el.value;
    cambiar(el.dataset.ruta, v, el.type === 'checkbox' || el.tagName === 'SELECT');
  });
  raiz.addEventListener('focusout', (e) => { if (e.target.closest('[data-ruta]') && reloj) { clearTimeout(reloj); enviar(); } });
  $('#ia_modo').addEventListener('click', (e) => { const v = e.target.dataset.v; if (v) { datos.ia.modo = v; pintarModo(); cambiar('ia.modo', v, true); } });
  $('#formatos').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-f]'); if (!b) return;
    for (const x of $('#formatos').children) x.classList.toggle('activo', x === b);
    for (const p of raiz.querySelectorAll('[data-panel]')) p.hidden = p.dataset.panel !== b.dataset.f;
  });

  // ── probar conexión: solo salud, nunca genera ──
  raiz.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-probar]'); if (!b) return;
    const que = b.dataset.probar, caja = $('#r_' + que);
    if (reloj) { clearTimeout(reloj); await enviar(); }
    await enVuelo;
    b.disabled = true; caja.className = 'resultado'; caja.textContent = t('ia.probando');
    try {
      const d = await (await fetch('/api/ia/probar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ que }) })).json();
      caja.className = 'resultado ' + (d.ok ? (d.estado === 'listo' || d.estado === 'responde' ? 'ok' : 'aviso') : 'mal');
      caja.textContent = t(`ia.salud.${que}.${d.estado}`) + (d.detalle && d.ok ? ` · ${d.detalle}` : '') + (d.ms ? ` · ${d.ms} ms` : '');
    } catch (_) { caja.className = 'resultado mal'; caja.textContent = t('desconectado'); }
    b.disabled = false;
  });

  const listo = (async () => {
    datos = await (await fetch('/api/proyecto')).json();
    $('#instruccion').textContent = (await (await fetch('/api/ia/instruccion')).json()).texto;
    pintar();
  })();
  return { activar: () => listo.then(pintar), datos: () => datos };
}
