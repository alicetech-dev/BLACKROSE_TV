// Render de una ESCENA (JSON) — el mismo código para /estudio (vista previa) y /salida (OBS).
// La escena llega del servidor por WebSocket; cada cambio se aplica sin recargar la página.
import * as THREE from 'three';
import { Avatar } from './avatar.js';

const CALIDAD = { bajo: { px: 0.75, aa: false }, medio: { px: 1, aa: true }, alto: { px: 1.25, aa: true } };

export async function crearEscena(contenedor, { ancho = 1920, alto = 1080, fijo = false, calidad = 'medio', alpha = false, planoFijo = null } = {}) {
  const Q = CALIDAD[calidad] || CALIDAD.medio;
  const renderer = new THREE.WebGLRenderer({ antialias: Q.aa, alpha, powerPreference: 'low-power', preserveDrawingBuffer: true });
  renderer.setPixelRatio(Q.px); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
  contenedor.appendChild(renderer.domElement);
  const escena3d = new THREE.Scene(); escena3d.background = alpha ? null : new THREE.Color(0x05040c);
  const camara = new THREE.PerspectiveCamera(40, ancho / alto, 0.05, 120);

  const ajustar = () => {                                   // /salida: lienzo fijo 1920×1080 · /estudio: llena el contenedor
    const w = fijo ? ancho : contenedor.clientWidth || ancho, h = fijo ? alto : Math.round(w * alto / ancho);
    renderer.setSize(w, h, !fijo); camara.aspect = w / h; camara.updateProjectionMatrix();
  };
  ajustar(); if (!fijo) new ResizeObserver(ajustar).observe(contenedor);

  const estado = { escena: null, set: null, setId: null, reparto: new Map(), plano: 'auto', planoAuto: null, tPlano: 0, foco: null, hablante: null };
  const oyentes = new Set();
  const avisar = () => { for (const f of oyentes) f(info()); };
  const info = () => ({ set: estado.setId, plano: estado.plano, activo: planoActivo(), planos: estado.set ? estado.set.orden.map((id) => ({ id, nombre: estado.set.camaras[id].nombre, tipo: estado.set.camaras[id].tipo })) : [] });

  async function cargarSet(id) {
    if (estado.setId === id) return;
    const mod = await import(`./sets/${encodeURIComponent(id)}.js`);
    if (estado.set) escena3d.remove(estado.set.grupo);
    estado.set = mod.crearSet(); estado.setId = id; escena3d.add(estado.set.grupo);
  }

  function sincronizarReparto(lista = []) {
    const vistos = new Set();
    for (const d of lista) {
      if (!d || !d.id) continue; vistos.add(d.id);
      let av = estado.reparto.get(d.id); if (!av) { av = new Avatar(escena3d, d); estado.reparto.set(d.id, av); } else av.actualizar(d);
      av.pos = d.pos; av.colocar(estado.set?.posiciones[d.pos] || [0, 0, 0, 0]);
    }
    for (const [id, av] of estado.reparto) if (!vistos.has(id)) { av.destruir(); estado.reparto.delete(id); }
  }

  async function aplicar(e) {
    estado.escena = e;
    await cargarSet(e.set || 'noticias');
    estado.set.aplicar(e);
    sincronizarReparto(e.reparto);
    fijarPlano(planoFijo || e.plano || 'auto');
    avisar();
  }

  function fijarPlano(id, forzar = false) {
    if (planoFijo && !forzar) id = planoFijo;             // ?plano= en la URL manda sobre el servidor
    if (id !== 'auto' && !estado.set?.camaras[id]) return;
    if (id === estado.plano) return;
    estado.plano = id; estado.tPlano = 0; avisar();
  }

  function hablar(id, on) {                                 // quién habla: la cámara frontal la encuadra
    for (const [k, av] of estado.reparto) av.hablando = on && k === id;
    estado.hablante = on ? id : null;
  }

  function planoActivo() {
    if (!estado.set) return null;
    return estado.plano === 'auto' ? (estado.planoAuto || estado.set.orden[0]) : estado.plano;
  }

  // ── bucle ────────────────────────────────────────────────────────────────
  const reloj = new THREE.Clock(); let t = 0, fps = 0, nCuadros = 0, tFps = 0;
  const DUR_AUTO = 8;
  function cuadro() {
    const dt = Math.min(0.1, reloj.getDelta()); t += dt;
    if (estado.set) {
      if (estado.plano === 'auto') {                        // rotación automática de planos, con corte seco
        estado.tPlano -= dt;
        if (estado.tPlano <= 0) {
          const o = estado.set.orden, i = o.indexOf(estado.planoAuto);
          estado.planoAuto = o[(i + 1) % o.length]; estado.tPlano = DUR_AUTO + Math.random() * 4; avisar();
        }
      }
      const id = planoActivo(), cam = estado.set.camaras[id];
      const habl = estado.hablante && estado.reparto.get(estado.hablante);
      const foco = habl ? estado.set.posiciones[habl.pos] : null;
      const p = cam.pose(t, foco);
      camara.position.copy(p.p); camara.lookAt(p.l);
      if (camara.fov !== p.fov) { camara.fov = p.fov; camara.updateProjectionMatrix(); }
      estado.set.update(t, dt);
      for (const av of estado.reparto.values()) av.update(t, dt, camara.position);
    }
    renderer.render(escena3d, camara);
    nCuadros++; tFps += dt; if (tFps >= 1) { fps = nCuadros / tFps; nCuadros = 0; tFps = 0; }
  }
  renderer.setAnimationLoop(cuadro);

  return {
    aplicar, fijarPlano, hablar, info,
    alCambiar: (f) => { oyentes.add(f); return () => oyentes.delete(f); },
    get fps() { return fps; },
    renderer, camara, escena3d,
  };
}

/** Conecta la escena al servidor: recibe {t:'escena'|'plano'|'habla'} y se reconecta sola. */
export function conectar(ctrl, { url = `ws://${location.host}/ws`, alEstado = () => {} } = {}) {
  let ws, vivo = true;
  const abrir = () => {
    ws = new WebSocket(url);
    ws.onopen = () => alEstado(true);
    ws.onclose = () => { alEstado(false); if (vivo) setTimeout(abrir, 1500); };
    ws.onmessage = (m) => {
      let d; try { d = JSON.parse(m.data); } catch (_) { return; }
      if (d.t === 'escena' && d.d) ctrl.aplicar(d.d);
      else if (d.t === 'plano') ctrl.fijarPlano(d.plano);
      else if (d.t === 'habla') ctrl.hablar(d.id, !!d.on);
    };
  };
  abrir();
  return { cerrar() { vivo = false; ws?.close(); } };
}
