// Ayudas de geometría y texturas compartidas por los sets (todo procedural: cero assets pesados).
import * as THREE from 'three';

export const mat = (c, e = 0, ei = 1, extra = {}) =>
  new THREE.MeshStandardMaterial({ color: c, emissive: e, emissiveIntensity: ei, roughness: 0.7, ...extra });
export const neon = (c, i = 1.6) => new THREE.MeshStandardMaterial({ color: 0x000000, emissive: c, emissiveIntensity: i, roughness: 1 });
export const basico = (c, extra = {}) => new THREE.MeshBasicMaterial({ color: c, ...extra });

export function ubicar(g, geo, m, x, y, z, ry = 0) {
  const o = new THREE.Mesh(geo, m); o.position.set(x, y, z); o.rotation.y = ry; g.add(o); return o;
}
export const caja = (g, w, h, d, m, x, y, z, ry = 0) => ubicar(g, new THREE.BoxGeometry(w, h, d), m, x, y, z, ry);
export const cil = (g, r1, r2, h, m, x, y, z, seg = 16) => ubicar(g, new THREE.CylinderGeometry(r1, r2, h, seg), m, x, y, z);

export function lienzo(w, h) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  return { c, g: c.getContext('2d'), tex };
}

/** Texto que cabe en el ancho dado (achica la fuente hasta que entra). */
export function ajustarTexto(g, texto, ancho, tam, peso = '800', familia = 'system-ui, sans-serif') {
  g.font = `${peso} ${tam}px ${familia}`;
  while (g.measureText(texto).width > ancho && tam > 8) { tam *= 0.93; g.font = `${peso} ${tam}px ${familia}`; }
  return tam;
}

/** Silueta low-poly de personal de fondo: cuerpo + cabeza + orejas (neko opcional). Devuelve geometrías para InstancedMesh. */
export function geometriasSilueta(orejas = true) {
  const cuerpo = new THREE.CapsuleGeometry(0.2, 0.75, 3, 8); cuerpo.translate(0, 0.62, 0);
  const cabeza = new THREE.SphereGeometry(0.14, 10, 8); cabeza.translate(0, 1.33, 0);
  const partes = [cuerpo, cabeza];
  if (orejas) {
    for (const s of [-1, 1]) { const o = new THREE.ConeGeometry(0.05, 0.12, 4); o.rotateZ(-s * 0.35); o.translate(s * 0.08, 1.48, 0); partes.push(o); }
  }
  return partes;
}

export const color = (c, def = 0xffffff) => { try { return new THREE.Color(c ?? def); } catch (_) { return new THREE.Color(def); } };
