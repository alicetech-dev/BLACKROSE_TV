// Vista previa de UN avatar (pantalla Mi Reparto): tocadiscos con luz de estudio, se gira arrastrando y se acerca con la rueda.
// Sirve también para sacar la miniatura (foto de la vista actual en PNG).
import * as THREE from 'three';
import { Avatar } from './avatar.js';

export function crearVistaAvatar(contenedor) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5)); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  contenedor.appendChild(renderer.domElement);
  const escena = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(30, 1, 0.05, 50);
  escena.add(new THREE.HemisphereLight(0xc8c8ff, 0x302040, 1.4));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(1.5, 2.5, 3); escena.add(key);
  const rim = new THREE.DirectionalLight(0xff4fd8, 1.6); rim.position.set(-2, 2, -2.5); escena.add(rim);
  const disco = new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.8, 0.05, 48), new THREE.MeshStandardMaterial({ color: 0x241a44, roughness: 0.35, metalness: 0.4 }));
  disco.position.y = -0.025; escena.add(disco);
  const aro = new THREE.Mesh(new THREE.TorusGeometry(0.79, 0.008, 6, 64), new THREE.MeshBasicMaterial({ color: 0x00e5ff })); aro.rotation.x = Math.PI / 2; escena.add(aro);

  let avatar = null, giro = 0.35, dist = 3.6, auto = true, arrastre = null;
  const ajustar = () => {
    const w = contenedor.clientWidth || 400, h = contenedor.clientHeight || 400;
    renderer.setSize(w, h, false); renderer.domElement.style.width = '100%'; renderer.domElement.style.height = '100%';
    cam.aspect = w / h; cam.updateProjectionMatrix();
  };
  ajustar(); new ResizeObserver(ajustar).observe(contenedor);

  const lienzo = renderer.domElement;
  lienzo.style.cursor = 'grab'; lienzo.style.touchAction = 'none';
  lienzo.addEventListener('pointerdown', (e) => { arrastre = e.clientX; auto = false; lienzo.setPointerCapture(e.pointerId); lienzo.style.cursor = 'grabbing'; });
  lienzo.addEventListener('pointermove', (e) => { if (arrastre === null) return; giro += (e.clientX - arrastre) * 0.01; arrastre = e.clientX; });
  lienzo.addEventListener('pointerup', () => { arrastre = null; lienzo.style.cursor = 'grab'; });
  lienzo.addEventListener('wheel', (e) => { e.preventDefault(); dist = THREE.MathUtils.clamp(dist * (1 + Math.sign(e.deltaY) * 0.1), 1.2, 6); }, { passive: false });
  lienzo.addEventListener('dblclick', () => { auto = !auto; });

  const reloj = new THREE.Clock(); let t = 0;
  renderer.setAnimationLoop(() => {
    const dt = Math.min(0.1, reloj.getDelta()); t += dt;
    if (auto) giro += dt * 0.35;
    const alto = avatar?.altura ?? 1.6, objetivo = alto * 0.55;
    cam.position.set(Math.sin(giro) * dist, objetivo + 0.15, Math.cos(giro) * dist); cam.lookAt(0, objetivo, 0);
    avatar?.update(t, dt, cam.position);
    renderer.render(escena, cam);
  });

  return {
    /** Carga un VRM (url) o nada (null → silueta). Devuelve true si el VRM quedó cargado. */
    async mostrar(url, color = '#ff6fb5') {
      if (avatar) { avatar.destruir(); avatar = null; }
      avatar = new Avatar(escena, { vrm: url, color });
      avatar.colocar([0, 0, 0, 0]);
      return avatar.cargando;
    },
    /** Foto de la vista actual de frente (PNG). */
    async foto(tam = 384) {
      const g0 = giro, d0 = dist, a0 = auto; giro = 0; dist = 1.25; auto = false;
      const alto = avatar?.altura ?? 1.6;
      cam.position.set(0, alto * 0.9, dist); cam.lookAt(0, alto * 0.87, 0);       // primer plano: cabeza y hombros
      avatar?.update(t, 0.016, cam.position);
      const w = lienzo.width, h = lienzo.height;
      renderer.setSize(tam, tam, false); cam.aspect = 1; cam.updateProjectionMatrix();
      renderer.render(escena, cam);
      const blob = await new Promise((ok) => lienzo.toBlob(ok, 'image/png'));
      renderer.setSize(w, h, false); ajustar();
      giro = g0; dist = d0; auto = a0;
      return blob;
    },
    destruir() { renderer.setAnimationLoop(null); avatar?.destruir(); renderer.dispose(); lienzo.remove(); },
  };
}
