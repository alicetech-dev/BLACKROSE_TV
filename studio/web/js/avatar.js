// Un integrante del reparto: VRM (0.x o 1.0) con vida procedural, o una silueta neko si aún no tiene VRM.
// Sin VMC: reposo con brazos abajo, respiración, parpadeo, mirada a la cámara activa, cabeceo y boca al hablar.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { mat, geometriasSilueta, color } from './util.js';

// Huesos normalizados de three-vrm (mismo marco para VRM 0.x y 1.0): el brazo izquierdo apunta a +X; rotar +Z lo baja.
const REPOSO = { leftUpperArm: [0, 0, 1.2], rightUpperArm: [0, 0, -1.2], leftLowerArm: [0, 0, 0.1], rightLowerArm: [0, 0, -0.1], leftHand: [0, 0, 0.06], rightHand: [0, 0, -0.06] };
const BOCA = ['aa', 'ih', 'ou', 'ee', 'oh'];
const cargador = new GLTFLoader(); cargador.register((p) => new VRMLoaderPlugin(p));
const q = new THREE.Quaternion(), eu = new THREE.Euler(), mirarA = new THREE.Vector3(), tmp = new THREE.Vector3();

export class Avatar {
  constructor(escena3d, datos) {
    this.root = new THREE.Group(); escena3d.add(this.root);
    this.vrm = null; this.url = null; this.ok = false; this.altura = 1.62;
    this.hablando = false; this.nivel = 0; this.parpado = 2 + Math.random() * 3; this.fase = Math.random() * 10; this.viseme = 'aa';
    this.silueta = this.crearSilueta(datos?.color);
    this.actualizar(datos || {});
  }

  crearSilueta(c) {
    const g = new THREE.Group(), m = mat(color(c, 0xff6fb5), 0, 1, { roughness: 0.5 });
    for (const geo of geometriasSilueta(true)) g.add(new THREE.Mesh(geo, m));
    g.scale.setScalar(this.altura / 1.55); this.root.add(g); return g;
  }

  /** Aplica nombre/vrm/altura/color de la escena. Solo recarga el VRM si cambió la URL. */
  actualizar(d) {
    if (d.altura_m) this.altura = +d.altura_m;
    if (d.color) this.silueta.children.forEach((m) => m.material.color.copy(color(d.color)));
    const url = d.vrm || null;
    if (url !== this.url) { this.url = url; this.cargar(url); }
  }

  async cargar(url) {
    if (this.vrm) { this.root.remove(this.vrm.scene); VRMUtils.deepDispose(this.vrm.scene); this.vrm = null; }
    this.ok = false; this.silueta.visible = true;
    if (!url) return;
    try {
      const gltf = await cargador.loadAsync(url);
      if (url !== this.url) return;                          // llegó otra mientras cargaba
      const vrm = gltf.userData.vrm; if (!vrm) throw new Error('no es VRM');
      VRMUtils.removeUnnecessaryVertices(gltf.scene); (VRMUtils.combineSkeletons || VRMUtils.removeUnnecessaryJoints)?.(gltf.scene); VRMUtils.rotateVRM0(vrm);
      vrm.scene.traverse((o) => { o.frustumCulled = false; if (o.isMesh) o.castShadow = false; });
      vrm.scene.updateMatrixWorld(true);
      const bb = new THREE.Box3().setFromObject(vrm.scene, true), alto = bb.max.y - bb.min.y;
      if (alto > 0.5) { const k = this.altura / alto; vrm.scene.scale.setScalar(k); vrm.scene.position.y = -bb.min.y * k; }
      this.exprs = {}; for (const ex of vrm.expressionManager?.expressions ?? []) { this.exprs[ex.expressionName.toLowerCase()] = ex.expressionName; ex.overrideMouth = 'none'; }
      for (const [n, r] of Object.entries(REPOSO)) vrm.humanoid.getNormalizedBoneNode(n)?.quaternion.setFromEuler(eu.set(r[0], r[1], r[2]));   // sin T-pose al aparecer
      vrm.update(0);
      this.root.add(vrm.scene); this.vrm = vrm; this.ok = true; this.silueta.visible = false;
    } catch (err) { console.warn('[avatar] no cargó', url, err); }
  }

  colocar([x, y, z, ry]) { this.root.position.set(x, y, z); this.root.rotation.y = ry || 0; }  // tras rotateVRM0 los VRM miran a +Z, donde están las cámaras

  /** nivel: 0..1 de la voz (WebAudio); camara: posición del plano activo para mirarla. */
  update(t, dt, camara) {
    if (!this.ok) {                                        // silueta: respira y se balancea apenas
      this.silueta.position.y = Math.sin(t * 1.6 + this.fase) * 0.01; this.silueta.rotation.y = Math.sin(t * 0.5 + this.fase) * 0.05; return;
    }
    const vrm = this.vrm, h = vrm.humanoid, a = Math.min(1, dt * 4);
    for (const [n, r] of Object.entries(REPOSO)) { const nodo = h.getNormalizedBoneNode(n); if (nodo) nodo.quaternion.slerp(q.setFromEuler(eu.set(r[0], r[1], r[2])), a); }
    const resp = Math.sin(t * 1.4 + this.fase);
    const sp = h.getNormalizedBoneNode('spine'); if (sp) sp.rotation.x = resp * 0.012;
    const ch = h.getNormalizedBoneNode('chest'); if (ch) ch.rotation.x = resp * 0.01;
    const cab = h.getNormalizedBoneNode('head');
    if (cab && camara) {                                   // mirar a cámara (limitado), con cabeceo al hablar
      cab.getWorldPosition(tmp); mirarA.copy(camara).sub(tmp);
      const inv = this.root.getWorldQuaternion(q).invert(); mirarA.applyQuaternion(inv);
      const yaw = THREE.MathUtils.clamp(Math.atan2(mirarA.x, mirarA.z), -0.5, 0.5), pitch = THREE.MathUtils.clamp(-Math.atan2(mirarA.y, Math.hypot(mirarA.x, mirarA.z)), -0.3, 0.3);
      const cabeceo = this.hablando ? Math.sin(t * 5.3 + this.fase) * 0.035 * (0.4 + this.nivel) : 0;
      cab.rotation.y += (yaw * 0.6 - cab.rotation.y) * a; cab.rotation.x += (pitch * 0.5 + cabeceo - cab.rotation.x) * a;
      cab.rotation.z = Math.sin(t * 0.7 + this.fase) * 0.03;
    }
    const em = vrm.expressionManager;
    if (em) {
      this.parpado -= dt; const blink = this.exprs.blink;
      if (blink) em.setValue(blink, this.parpado < 0 && this.parpado > -0.14 ? 1 : 0);
      if (this.parpado < -0.14) this.parpado = 2.2 + Math.random() * 4;
      const abre = this.hablando ? Math.min(1, this.nivel * 1.6) : 0;
      if (this.hablando && Math.random() < dt * 9) this.viseme = BOCA[(Math.random() * BOCA.length) | 0];
      for (const b of BOCA) { const n = this.exprs[b]; if (n) em.setValue(n, b === this.viseme ? abre : Math.max(0, em.getValue(n) - dt * 8)); }
    }
    vrm.update(dt);
  }

  destruir() { if (this.vrm) VRMUtils.deepDispose(this.vrm.scene); this.root.parent?.remove(this.root); }
}
