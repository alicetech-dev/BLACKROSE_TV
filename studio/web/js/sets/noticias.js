// SET DE NOTICIAS (procedural). Ejes: la mesa está en el origen, las cámaras miran hacia −Z desde +Z.
//   · mesa curva de conducción con franja de color de la marca
//   · video wall gigante con nombre del canal + titular (textura de canvas)
//   · ventanal a la ciudad (noche/día) sobre el video wall
//   · sala de prensa a la izquierda: escritorios con monitores y personal de fondo (InstancedMesh)
//   · piso del estudio: cámaras de pedestal con camarógrafas y una operadora de vara con micrófono
// Interfaz que espera escena.js: { grupo, camaras, posiciones, luces, aplicar(escena), update(t, dt) }
import * as THREE from 'three';
import { mat, neon, basico, caja, cil, lienzo, ajustarTexto, geometriasSilueta, color } from '../util.js';

export const ID = 'noticias';
export const NOMBRE = 'Noticias';

export function crearSet() {
  const grupo = new THREE.Group();
  const prim = mat(0xff2fd6), sec = mat(0x00e5ff);          // se recolorean en aplicar()
  const franjaP = neon(0xff2fd6, 2.2), franjaS = neon(0x00e5ff, 1.8);

  // ── piso y concha del estudio ─────────────────────────────────────────────
  const pisoTex = lienzo(1024, 1024);
  { const g = pisoTex.g; g.fillStyle = '#0d0b1a'; g.fillRect(0, 0, 1024, 1024); g.strokeStyle = '#2a2350'; g.lineWidth = 3;
    for (let i = 0; i <= 1024; i += 64) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 1024); g.stroke(); g.beginPath(); g.moveTo(0, i); g.lineTo(1024, i); g.stroke(); } }
  pisoTex.tex.wrapS = pisoTex.tex.wrapT = THREE.RepeatWrapping; pisoTex.tex.repeat.set(6, 5);
  const piso = new THREE.Mesh(new THREE.PlaneGeometry(32, 26), new THREE.MeshStandardMaterial({ map: pisoTex.tex, roughness: 0.25, metalness: 0.4 }));
  piso.rotation.x = -Math.PI / 2; piso.position.z = 1; grupo.add(piso);
  // tarima circular bajo la mesa
  cil(grupo, 3.4, 3.5, 0.12, mat(0x1a1530, 0, 1, { roughness: 0.3, metalness: 0.5 }), 0, 0.06, -0.3, 48);
  const aro = new THREE.Mesh(new THREE.TorusGeometry(3.45, 0.025, 6, 96), franjaP); aro.rotation.x = Math.PI / 2; aro.position.set(0, 0.13, -0.3); grupo.add(aro);
  const pared = mat(0x15122a, 0, 1, { roughness: 0.6 });
  caja(grupo, 32, 7, 0.3, pared, 0, 3.5, -6);              // pared de fondo
  caja(grupo, 0.3, 7, 14, pared, 15.5, 3.5, 0);             // pared derecha
  caja(grupo, 32, 0.2, 16, basico(0x07060e), 0, 7, -0.5);  // techo

  // ── ventanal a la ciudad (arriba del video wall) ──────────────────────────
  const ciudad = lienzo(2048, 512);
  const pintarCiudad = (noche) => {
    const g = ciudad.g, W = 2048, H = 512;
    const cielo = g.createLinearGradient(0, 0, 0, H);
    if (noche) { cielo.addColorStop(0, '#05030f'); cielo.addColorStop(1, '#2b0d3d'); } else { cielo.addColorStop(0, '#6fb6ff'); cielo.addColorStop(1, '#ffd9ef'); }
    g.fillStyle = cielo; g.fillRect(0, 0, W, H);
    let s = 7; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;   // determinista: la ciudad no cambia entre recargas
    for (let x = 0; x < W;) {
      const w = 40 + rnd() * 110, h = 120 + rnd() * 330;
      g.fillStyle = noche ? '#0b0918' : '#5a6a8a'; g.fillRect(x, H - h, w, h);
      g.fillStyle = noche ? (rnd() > 0.5 ? '#ff6fd8' : '#7fe9ff') : '#cfe3ff';
      for (let wy = H - h + 10; wy < H - 8; wy += 18) for (let wx = x + 6; wx < x + w - 8; wx += 14) if (rnd() > (noche ? 0.55 : 0.75)) g.fillRect(wx, wy, 6, 8);
      x += w + 4;
    }
    ciudad.tex.needsUpdate = true;
  };
  const ventanal = new THREE.Mesh(new THREE.PlaneGeometry(22, 5.5), new THREE.MeshBasicMaterial({ map: ciudad.tex, toneMapped: false }));
  ventanal.position.set(0, 4.6, -5.8); grupo.add(ventanal);
  for (let i = -5; i <= 5; i++) caja(grupo, 0.08, 5.6, 0.12, mat(0x0a0814, 0, 1, { metalness: 0.8, roughness: 0.3 }), i * 2.2, 4.6, -5.75);   // parteluces

  // ── video wall con canal + titular ───────────────────────────────────────
  const vw = lienzo(2048, 900);
  const estadoVW = { canal: '', titular: '', primario: '#ff2fd6', secundario: '#00e5ff' };
  const pintarVW = (t = 0) => {
    const g = vw.g, W = 2048, H = 900, { canal, titular, primario, secundario } = estadoVW;
    const fondo = g.createLinearGradient(0, 0, W, H); fondo.addColorStop(0, '#0a0620'); fondo.addColorStop(1, '#1d0830'); g.fillStyle = fondo; g.fillRect(0, 0, W, H);
    g.globalAlpha = 0.18; g.strokeStyle = secundario; g.lineWidth = 2;                              // retícula que se desliza
    const off = (t * 40) % 80; for (let x = -80 + off; x < W; x += 80) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x + 200, H); g.stroke(); }
    g.globalAlpha = 1; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.shadowColor = primario; g.shadowBlur = 40; g.fillStyle = '#fff';
    ajustarTexto(g, canal || ' ', W * 0.86, 230, '900'); g.fillText(canal, W / 2, titular ? H * 0.36 : H / 2);
    if (titular) {
      g.shadowBlur = 0; g.fillStyle = primario; g.fillRect(0, H * 0.66, W, H * 0.22);
      g.fillStyle = '#fff'; ajustarTexto(g, titular, W * 0.9, 110, '800'); g.fillText(titular, W / 2, H * 0.77);
    }
    vw.tex.needsUpdate = true;
  };
  caja(grupo, 9.4, 3.9, 0.25, mat(0x050409, 0, 1, { metalness: 0.7, roughness: 0.3 }), 0, 1.95 + 0.25, -5.6);
  const pantalla = new THREE.Mesh(new THREE.PlaneGeometry(9, 3.95 * 0.95), new THREE.MeshBasicMaterial({ map: vw.tex, toneMapped: false }));
  pantalla.position.set(0, 2.2, -5.45); grupo.add(pantalla);
  const marcoVW = caja(grupo, 9.4, 0.06, 0.06, franjaS, 0, 0.32, -5.4); void marcoVW;
  caja(grupo, 9.4, 0.06, 0.06, franjaS, 0, 4.1, -5.4);

  // ── mesa curva de conducción ─────────────────────────────────────────────
  // Arco de anillo con centro detrás de las conductoras: su cara frontal (x=0) queda en z=+0.4, mirando a cámara.
  const Ri = 2.25, Ro = 2.6, ARC = 1.15, ZC = 0.4 - Ro;
  const mesa = new THREE.Group(); mesa.position.set(0, 0.12, ZC); grupo.add(mesa);
  const tapa = new THREE.Mesh(new THREE.RingGeometry(Ri, Ro + 0.04, 48, 1, -Math.PI / 2 - ARC / 2, ARC), mat(0xf4f0ff, 0, 1, { roughness: 0.15, metalness: 0.2, side: THREE.DoubleSide }));
  tapa.rotation.x = -Math.PI / 2; tapa.position.y = 0.86;   // tope a 0,98 m: mesa de conducción de pie
  const frente = new THREE.Mesh(new THREE.CylinderGeometry(Ro, Ro, 0.86, 48, 1, true, -ARC / 2, ARC), mat(0x1a1430, 0, 1, { side: THREE.DoubleSide, metalness: 0.6, roughness: 0.35 }));
  frente.position.y = 0.43;
  const franja = new THREE.Mesh(new THREE.CylinderGeometry(Ro + 0.01, Ro + 0.01, 0.07, 48, 1, true, -ARC / 2, ARC), franjaP);
  franja.position.y = 0.72;
  const zocalo = new THREE.Mesh(new THREE.CylinderGeometry(Ro + 0.01, Ro + 0.01, 0.04, 48, 1, true, -ARC / 2, ARC), franjaS);
  zocalo.position.y = 0.04;
  mesa.add(tapa, frente, franja, zocalo);
  // logo en el frente de la mesa
  const logoTex = lienzo(1024, 256);
  const logo = new THREE.Mesh(new THREE.PlaneGeometry(1.7, 0.42), new THREE.MeshBasicMaterial({ map: logoTex.tex, transparent: true, toneMapped: false }));
  logo.position.set(0, 0.45, 0.42); grupo.add(logo);
  const pintarLogo = () => { const g = logoTex.g; g.clearRect(0, 0, 1024, 256); g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = '#fff'; g.shadowColor = estadoVW.primario; g.shadowBlur = 24; ajustarTexto(g, estadoVW.canal || ' ', 980, 150, '900'); g.fillText(estadoVW.canal, 512, 128); logoTex.tex.needsUpdate = true; };
  // monitores de la mesa
  for (const x of [-1.25, 1.25]) { const m = caja(grupo, 0.36, 0.22, 0.02, neon(0x5fd8ff, 0.9), x, 1.1, 0.0); m.rotation.x = -0.45; m.rotation.y = x > 0 ? 0.35 : -0.35; }

  // ── sala de prensa (izquierda), detrás de un vidrio ──────────────────────
  const prensa = new THREE.Group(); prensa.position.set(-10, 0, -1.2); grupo.add(prensa);
  const vidrio = new THREE.Mesh(new THREE.PlaneGeometry(8.5, 3.4), new THREE.MeshStandardMaterial({ color: 0x88ccff, transparent: true, opacity: 0.1, roughness: 0.05, metalness: 0.9 }));
  vidrio.position.set(4.6, 1.7, 0.5); vidrio.rotation.y = Math.PI / 2; prensa.add(vidrio);
  caja(prensa, 0.06, 0.06, 8.5, franjaS, 4.6, 3.4, 0.5); caja(prensa, 0.06, 0.06, 8.5, franjaS, 4.6, 0.05, 0.5);
  for (let z = -3.75; z <= 4.75; z += 2.125) caja(prensa, 0.08, 3.4, 0.08, metalP(), 4.6, 1.7, z);
  caja(prensa, 0.3, 7, 14, mat(0x15122a, 0, 1, { roughness: 0.6 }), -5.5, 3.5, 0);        // pared izquierda
  for (const z of [-3, -0.9, 1.2]) caja(prensa, 7.5, 0.05, 0.5, neon(0xe8ecff, 1.4), -0.3, 3.3, z);  // paneles de luz del techo
  function metalP() { return mat(0x202028, 0, 1, { metalness: 0.8, roughness: 0.35 }); }
  const escritorio = mat(0x2a2444, 0, 1, { roughness: 0.4 });
  const pantallas = [];
  const puestos = [];
  for (let fila = 0; fila < 3; fila++) for (let col = 0; col < 4; col++) {
    const x = -2.6 + col * 1.9, z = -3 + fila * 2.1;
    caja(prensa, 1.5, 0.05, 0.7, escritorio, x, 0.75, z); caja(prensa, 0.05, 0.75, 0.6, escritorio, x - 0.7, 0.375, z); caja(prensa, 0.05, 0.75, 0.6, escritorio, x + 0.7, 0.375, z);
    for (const dx of [-0.35, 0.35]) { const m = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.3), neon((fila + col) % 2 ? 0x00e5ff : 0xff6fd8, 1.1)); m.position.set(x + dx, 1.0, z - 0.25); prensa.add(m); pantallas.push(m); }
    puestos.push([x, z + 0.55]);
  }

  // ── personal de fondo (InstancedMesh: una sola llamada de dibujo por parte) ──
  const PERSONAL = [];
  for (const [x, z] of puestos) PERSONAL.push({ x: prensa.position.x + x, z: prensa.position.z + z, ry: Math.PI, sentada: true });
  PERSONAL.push({ x: -5.2, z: 4.4, ry: 0.5, sentada: false }, { x: 5.0, z: 4.6, ry: -0.45, sentada: false },     // camarógrafas
                { x: -3.2, z: 2.0, ry: 0.9, sentada: false }, { x: 8.5, z: -2.5, ry: -1.2, sentada: false },   // vara con micrófono, productora
                { x: 10.5, z: 1.5, ry: -1.4, sentada: false }, { x: 11.2, z: 3.2, ry: -1.8, sentada: false });
  const ropa = mat(0x4a3a78, 0, 1, { roughness: 0.7 }), piel = mat(0xb3a3e0, 0, 1, { roughness: 0.7 });
  const partes = geometriasSilueta(true).map((geo, i) => {
    const im = new THREE.InstancedMesh(geo, i === 0 ? ropa : piel, PERSONAL.length); grupo.add(im); return im;
  });
  const m4 = new THREE.Matrix4(), qq = new THREE.Quaternion(), eje = new THREE.Vector3(0, 1, 0), esc = new THREE.Vector3(1, 1, 1), pos = new THREE.Vector3();
  const colocarPersonal = (t) => {
    PERSONAL.forEach((p, i) => {
      const bob = Math.sin(t * 1.7 + i * 1.3) * 0.015;
      pos.set(p.x, (p.sentada ? -0.35 : 0) + bob, p.z); qq.setFromAxisAngle(eje, p.ry + Math.sin(t * 0.4 + i) * 0.08); esc.set(1, p.sentada ? 0.95 : 1, 1);
      m4.compose(pos, qq, esc); for (const im of partes) im.setMatrixAt(i, m4);
    });
    for (const im of partes) im.instanceMatrix.needsUpdate = true;
  };
  colocarPersonal(0);

  // ── cámaras de pedestal (utilería visible) y vara con micrófono ─────────
  const metal = mat(0x202028, 0, 1, { metalness: 0.8, roughness: 0.35 });
  const camaraPedestal = (x, z, ry) => {
    const c = new THREE.Group(); c.position.set(x, 0, z); c.rotation.y = ry; grupo.add(c);
    cil(c, 0.35, 0.4, 0.12, metal, 0, 0.06, 0, 12); cil(c, 0.06, 0.06, 1.25, metal, 0, 0.7, 0, 8);
    caja(c, 0.32, 0.3, 0.55, mat(0x111118), 0, 1.45, 0); cil(c, 0.1, 0.12, 0.25, metal, 0, 1.45, -0.38).rotation.x = Math.PI / 2;
    caja(c, 0.22, 0.16, 0.02, neon(0xff2f4f, 2), 0, 1.65, 0.1);     // tally rojo
    caja(c, 0.5, 0.03, 0.03, metal, 0.25, 1.32, 0.35);              // manilla
    return c;
  };
  camaraPedestal(-4.7, 3.9, 0.5 + Math.PI); camaraPedestal(4.5, 4.1, -0.45 + Math.PI);
  // vara con micrófono: sale de la mano de la operadora (−3.2, 0, 2.0) y cuelga sobre la conductora izquierda
  { const mano = new THREE.Vector3(-3.0, 1.9, 1.75), punta = new THREE.Vector3(-0.85, 3.05, -0.15);   // alta: fuera del plano frontal
    const dir = punta.clone().sub(mano), largo = dir.length();
    const vara = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, largo, 6), metal);
    vara.position.copy(mano).addScaledVector(dir, 0.5); vara.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize()); grupo.add(vara);
    const mic = cil(grupo, 0.045, 0.045, 0.26, mat(0x3a3a4a), punta.x, punta.y - 0.1, punta.z, 8); mic.rotation.x = 0.4; }

  // ── parrilla de luces del techo (visual) ─────────────────────────────────
  for (const z of [-2.5, 1.5]) {
    caja(grupo, 16, 0.08, 0.08, metal, 0, 6.2, z);
    for (let x = -7; x <= 7; x += 2) { const f = cil(grupo, 0.12, 0.16, 0.3, metal, x, 5.95, z, 8); f.rotation.x = 0.5; ubicarLente(grupo, x, 5.82, z + 0.08); }
  }
  function ubicarLente(g, x, y, z) { const l = new THREE.Mesh(new THREE.CircleGeometry(0.11, 10), basico(0xfff2dd, { toneMapped: false })); l.position.set(x, y, z); l.rotation.x = Math.PI / 2 + 0.5; g.add(l); }

  // ── luces reales: key / fill / rim + ambiente ───────────────────────────
  const hemi = new THREE.HemisphereLight(0x9aa0e8, 0x221828, 0.8); grupo.add(hemi);
  const key = new THREE.SpotLight(0xfff4ea, 60, 18, 0.55, 0.6, 1.4); key.position.set(-3, 5, 5); key.target.position.set(0, 1.2, 0); grupo.add(key, key.target);
  const fill = new THREE.SpotLight(0xdde8ff, 25, 18, 0.7, 0.8, 1.4); fill.position.set(3.5, 3.5, 5); fill.target.position.set(0, 1.2, 0); grupo.add(fill, fill.target);
  const rim = new THREE.SpotLight(0xff2fd6, 45, 14, 0.7, 0.7, 1.4); rim.position.set(0, 4.5, -3.5); rim.target.position.set(0, 1.3, 0.3); grupo.add(rim, rim.target);
  const prensaLuz = new THREE.PointLight(0xdfe8ff, 45, 14, 1.2); prensaLuz.position.set(-10, 3.0, -1.0); grupo.add(prensaLuz);
  const prensaLuz2 = new THREE.PointLight(0xff9ae6, 18, 10, 1.2); prensaLuz2.position.set(-7, 2.5, 2.5); grupo.add(prensaLuz2);
  const luces = { hemi, key, fill, rim };
  const BASE = { key: 60, fill: 25, rim: 45 };

  // ── planos de cámara ─────────────────────────────────────────────────────
  // pose(t, foco) → {p, l, fov}. foco = posición [x,y,z] de quien habla (o null).
  const v = (x, y, z) => new THREE.Vector3(x, y, z);
  const camaras = {
    frontal: { nombre: 'Frontal', tipo: 'fija', pose: (t, foco) => {
      const fx = foco ? foco[0] : 0; const cerca = !!foco;
      return { p: v(fx * 0.9, cerca ? 1.55 : 1.62, cerca ? 3.0 : 4.2), l: v(fx, cerca ? 1.38 : 1.3, -0.4), fov: cerca ? 20 : 29 };
    } },
    dos: { nombre: 'Plano general', tipo: 'movil', pose: (t) => {
      const d = Math.sin(t * 0.07) * 0.6;                    // dolly lateral muy lento
      return { p: v(3.4 + d, 2.1, 6.4), l: v(-0.4, 1.4, -1.4), fov: 42 };
    } },
    grua: { nombre: 'Grúa', tipo: 'movil', pose: (t) => {
      const a = Math.sin(t * 0.09) * 0.75 - 0.15, r = 8.2, h = 3.2 + Math.sin(t * 0.13) * 1.1;
      return { p: v(Math.sin(a) * r, h, Math.cos(a) * r - 0.5), l: v(-0.8, 1.1, -1.2), fov: 50 };
    } },
    prensa: { nombre: 'Sala de prensa', tipo: 'movil', pose: (t) => {
      const d = Math.sin(t * 0.11) * 1.4;
      return { p: v(-6.1, 2.0, 3.4 + d * 0.2), l: v(-11 + d, 1.0, -2.2), fov: 50 };
    } },
  };

  // ── dónde se paran las conductoras (x, y, z, rotación y) ────────────────
  const posiciones = {
    mesa_izq: [-0.72, 0.12, -0.4, 0.08], mesa_der: [0.72, 0.12, -0.4, -0.08], mesa_centro: [0, 0.12, -0.45, 0],
    pie_wall: [-3.2, 0, -4.2, 0.35], prensa: [-6.2, 0, 0.2, 0.6],
  };

  function aplicar(e) {
    const c = e.colores || {};
    estadoVW.primario = c.primario || '#ff2fd6'; estadoVW.secundario = c.secundario || '#00e5ff';
    estadoVW.canal = e.canal ?? ''; estadoVW.titular = e.titular ?? '';
    franjaP.emissive.copy(color(estadoVW.primario)); franjaS.emissive.copy(color(estadoVW.secundario));
    prim.color.copy(color(estadoVW.primario)); sec.color.copy(color(estadoVW.secundario));
    const L = e.luces || {};
    key.intensity = BASE.key * (L.key ?? 1); fill.intensity = BASE.fill * (L.fill ?? 1); rim.intensity = BASE.rim * (L.rim ?? 1);
    rim.color.copy(color(L.rim_color || estadoVW.primario));
    const noche = (e.ambiente || 'noche') !== 'dia';
    hemi.intensity = noche ? 0.8 : 1.6; hemi.color.copy(color(noche ? 0x9aa0e8 : 0xfff2e8));
    pintarCiudad(noche); pintarVW(0); pintarLogo();
  }

  let tVW = 0;
  function update(t, dt) {
    colocarPersonal(t);
    tVW += dt; if (tVW > 0.25) { tVW = 0; pintarVW(t); }     // el video wall se repinta a 4 cps (barato)
    for (let i = 0; i < pantallas.length; i++) pantallas[i].material.emissiveIntensity = 0.9 + 0.25 * Math.sin(t * 3 + i * 2.1);
  }

  return { grupo, camaras, posiciones, luces, aplicar, update, orden: ['frontal', 'dos', 'grua', 'prensa'] };
}
