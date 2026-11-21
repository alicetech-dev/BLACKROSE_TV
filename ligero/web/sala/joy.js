// El cuarto de Joy en el Bimbo Institute, versión SAFE para el canal: el cuarto 8×8 de joy_vmc (vr.js cuarto()) con la cama
// doble, el tocador y la guirnalda de cuarto69.js (que se leen del juego, sin copiarlos). Sin el «69», sin Bambi, sin
// cartelitos ni escenas adultas. La tele de la derecha muestra el canal (al aire, título y hora).
import * as THREE from 'three';
import { crearCuarto69 } from '/mundo/cuarto69.js';

export const TELE_Z = 1.2;

export function crearCuartoJoy({ canal }) {
  const g = new THREE.Group(); g.name = 'cuartoJoy';
  const mat = (c, e = 0, ei = 1) => new THREE.MeshStandardMaterial({ color: c, emissive: e, emissiveIntensity: ei, roughness: 0.8 });
  const caja = (w, h, d, m, x, y, z) => { const o = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); o.position.set(x, y, z); g.add(o); return o; };
  const neon = (col) => new THREE.MeshBasicMaterial({ color: col });

  // piso de madera oscura con tablas
  const c = document.createElement('canvas'); c.width = c.height = 512; const cg = c.getContext('2d');
  for (let i = 0; i < 16; i++) { cg.fillStyle = `hsl(228, 30%, ${14 + (i * 37 % 7)}%)`; cg.fillRect(0, i * 32, 512, 31); }
  const tex = new THREE.CanvasTexture(c); tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(3, 3); tex.colorSpace = THREE.SRGBColorSpace;
  const piso = new THREE.Mesh(new THREE.PlaneGeometry(8, 8), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.6 }));
  piso.rotation.x = -Math.PI / 2; g.add(piso);
  const pared = mat(0x2a0f3d);
  caja(8, 3.2, 0.1, pared, 0, 1.6, -2.5); caja(0.1, 3.2, 8, pared, -3.5, 1.6, 0); caja(0.1, 3.2, 8, pared, 3.5, 1.6, 0);
  caja(8, 0.1, 8, mat(0x0b0d24), 0, 3.2, 0);
  // tiras de neón en el zócalo y el techo
  caja(7, 0.03, 0.03, neon(0xff4fb8), 0, 0.05, -2.44); caja(7, 0.03, 0.03, neon(0x39d0ff), 0, 3.1, -2.44);
  caja(0.03, 0.03, 7, neon(0x39d0ff), -3.44, 0.05, 0); caja(0.03, 0.03, 7, neon(0xff4fb8), 3.44, 0.05, 0);
  // escritorio gamer con monitor y torre
  caja(1.6, 0.05, 0.6, mat(0x1a1d40), 2.2, 0.75, -2.1); caja(0.9, 0.5, 0.04, mat(0x000000, 0x2a6cff, 0.6), 2.2, 1.1, -2.3);
  caja(0.25, 0.5, 0.45, mat(0x0d0f25, 0x39d0ff, 0.35), 3.1, 1.02, -2.1);
  caja(1.6, 0.03, 0.6, neon(0x39d0ff), 2.2, 0.72, -2.1);
  // estrella de neón y estrellitas en la pared
  const est = new THREE.Shape();
  for (let i = 0; i < 10; i++) { const r = i % 2 ? 0.16 : 0.38, a = Math.PI / 2 + i * Math.PI / 5; (i ? est.lineTo : est.moveTo).call(est, Math.cos(a) * r, Math.sin(a) * r); }
  const estrella = new THREE.Mesh(new THREE.ShapeGeometry(est), neon(0xffc940)); estrella.position.set(1.2, 2.1, -2.44); g.add(estrella);
  for (let i = 0; i < 26; i++) {
    const s = new THREE.Mesh(new THREE.CircleGeometry(0.015 + Math.random() * 0.02, 6), neon([0x9ab8ff, 0xff9ad8, 0xffe07a][i % 3]));
    s.position.set(-3 + Math.random() * 6, 1.4 + Math.random() * 1.6, -2.44); g.add(s);
  }
  // tele en la pared derecha, mueble y un sillón enfrente; la tele muestra el canal
  caja(0.06, 1.36, 2.32, mat(0x05050a), 3.43, 1.55, TELE_Z);
  const tv = document.createElement('canvas'); tv.width = 1024; tv.height = 548; const tg = tv.getContext('2d');
  const tvTex = new THREE.CanvasTexture(tv); tvTex.colorSpace = THREE.SRGBColorSpace;
  const pant = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 2.2 * 548 / 1024), new THREE.MeshBasicMaterial({ map: tvTex, toneMapped: false }));
  pant.position.set(3.395, 1.55, TELE_Z); pant.rotation.y = -Math.PI / 2; g.add(pant);
  caja(0.42, 0.42, 1.9, mat(0x1a1d40), 3.24, 0.21, TELE_Z); caja(0.02, 0.03, 1.9, neon(0xff4fb8), 3.02, 0.4, TELE_Z);
  const tela = mat(0x5a2a7a);
  caja(0.75, 0.42, 1.7, tela, -0.8, 0.21, TELE_Z); caja(0.2, 0.9, 1.7, tela, -1.25, 0.45, TELE_Z);
  caja(0.75, 0.62, 0.18, tela, -0.82, 0.31, TELE_Z - 0.85); caja(0.75, 0.62, 0.18, tela, -0.82, 0.31, TELE_Z + 0.85);
  caja(0.5, 0.12, 1.4, mat(0x7b3fa0), -0.75, 0.48, TELE_Z);
  const alf = new THREE.Mesh(new THREE.CircleGeometry(1.3, 48), mat(0x3a1f5c, 0xff4fb8, 0.08)); alf.rotation.x = -Math.PI / 2; alf.position.set(1.6, 0.005, TELE_Z); g.add(alf);
  // luces: ambiente azul, contraluces de neón y una principal cálida sobre las dolls
  g.add(new THREE.HemisphereLight(0x6a78ff, 0x1a1030, 0.65));
  const p1 = new THREE.PointLight(0xff4fb8, 4.2, 7); p1.position.set(-1.8, 2.4, -1.6); g.add(p1);
  const p2 = new THREE.PointLight(0x39d0ff, 4.2, 7); p2.position.set(2.2, 2.2, -1.6); g.add(p2);
  const key = new THREE.DirectionalLight(0xffe6ee, 1.05); key.position.set(0.8, 2.6, 3); g.add(key);

  // el cartel de la pared, sin el «69»
  const cartel = (lineas, w, h, col) => {
    const cv = document.createElement('canvas'); cv.width = 1024; cv.height = 1024 * h / w; const q = cv.getContext('2d');
    q.textAlign = 'center'; q.textBaseline = 'middle'; q.shadowColor = col; q.fillStyle = '#fff';
    lineas.forEach(([t, px], i) => { q.font = `bold ${px}px "Brush Script MT", cursive, system-ui`; for (const b of [40, 20, 6]) { q.shadowBlur = b; q.fillText(t, 512, cv.height * (i + 0.5) / lineas.length); } });
    const tx = new THREE.CanvasTexture(cv); tx.colorSpace = THREE.SRGBColorSpace;
    return new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tx, transparent: true, toneMapped: false }));
  };
  const ct = cartel([['Joy’s Room', 150], ['♥ Bimbo Institute ♥', 90]], 2.4, 1.0, '#ff4fb8'); ct.position.set(0.55, 2.6, -2.43); g.add(ct);
  const h = new THREE.Shape();                      // corazón de neón en la pared izquierda
  h.moveTo(0, -0.3); h.bezierCurveTo(-0.45, 0, -0.35, 0.35, 0, 0.18); h.bezierCurveTo(0.35, 0.35, 0.45, 0, 0, -0.3);
  const cor = new THREE.Mesh(new THREE.ShapeGeometry(h, 24), neon(0xff4fb8)); cor.position.set(-3.44, 1.9, -1.2); cor.rotation.y = Math.PI / 2; g.add(cor);
  const n = 260, pos = new Float32Array(n * 3);      // brillitos rosas y dorados flotando
  for (let i = 0; i < n; i++) pos.set([-3.2 + Math.random() * 6.4, Math.random() * 3, -2.3 + Math.random() * 5.8], i * 3);
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const brillos = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xffb3e6, size: 0.018, transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending, depthWrite: false }));
  g.add(brillos);

  // la cama doble, el tocador y la guirnalda (cuarto69.js los cuelga de un grupo «dormitorio»)
  const cuarto69 = crearCuarto69({ dormitorio: g });

  // la manta sobre Alice: tapada hasta el cuello (así el avatar que duerme es safe sea cual sea el modelo). Solo se ve si duerme.
  const manta = new THREE.Mesh(new THREE.CapsuleGeometry(0.21, 1.1, 8, 20), new THREE.MeshStandardMaterial({ color: 0xffa6d6, roughness: 0.5, metalness: 0.1 }));
  manta.rotation.x = Math.PI / 2; manta.scale.set(1.45, 1, 0.85); manta.position.set(-2.0, 0.85, -1.23); manta.visible = false; g.add(manta);
  let t = 0, tvT = 0;
  return {
    grupo: g, manta,
    actualizar(dt, dormida = false) {
      t += dt; cuarto69.actualizar(dt, dormida);
      brillos.rotation.y = Math.sin(t * 0.07) * 0.05; brillos.position.y = Math.sin(t * 0.4) * 0.03;
      cor.scale.setScalar(1 + 0.05 * Math.sin(t * 2.2));
      if ((tvT -= dt) <= 0) { tvT = 0.5; canal.pintarTele(tg, 1024, 548); tvTex.needsUpdate = true; }
    },
  };
}
