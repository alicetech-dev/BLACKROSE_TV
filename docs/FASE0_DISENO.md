# Studio Manager — Fase 0: auditoría y diseño

Estado: 2026-11-21. Respuesta a `docs/PROMPT_STUDIO_MANAGER.md`. Esta fase no toca producción (`joy_vmc` sigue al aire).

## 1. Qué se reutiliza del repo

| Pieza existente | Qué aporta | Cómo entra al Studio |
|---|---|---|
| `ligero/web/vendor/` (three.js r169 + `@pixiv/three-vrm`, locales) | Motor WebGL sin CDN; el navegador de OBS Flatpak no llega a los CDN | Se usa tal cual en `/estudio` y `/salida` |
| `ligero/web/sala.html` (clase Doll) | Carga VRM 0.x/1.0, normaliza la altura, rotateVRM0, parpadeo, pose de reposo, expresiones | Se extrae a `studio/web/js/avatar.js` |
| `ligero/web/sala/*.js` (y `hacker.js`, que sigue en `joy_vmc/vr/web`) | Escenarios procedurales (geometría en código, sin assets pesados) | Sirven de patrón para `sets/*.js` |
| `director/tv/instalaciones.py` | Catálogo de los 8 sets con sus planos (amplio, dos, grúa, lateral, redacción…) | Se convierte en plantillas JSON de set; las medidas y planos de Unity son la referencia |
| `director/tv/fractal.py` | Receta programa → tema → formato → **tramo de ~50 s** con plantilla de respaldo si el LLM falla | El "tramo" es la unidad de checkpoint y regeneración del Studio |
| `director/tv/productor.py` (`llm_con`, `limpia`, `lineas_ok`) | Llamada al LLM con JSON robusto y limpieza de líneas | Se importa desde el generador de guiones |
| `ligero/cerebro.py` (:8087, OpenAI-compatible) | Router local 4B ⇄ 9B con failover | Es el proveedor "Local"; el "Online" va detrás de la misma interfaz |
| `director/voz.py` (Piper, Edge, XTTS, ConRespaldo) | Voces intercambiables, salida float32 | Proveedor de voz del Studio (Piper = offline por defecto) |
| `director/cache_voz.py` | Caché por perfil con **tiempos por palabra** | Evita resintetizar al regenerar un tramo; los tiempos dan el lipsync |
| `tools/obsws.py` | Cliente obs-websocket mínimo | Grabación: escena → StartRecord → StopRecord |
| `show_kuroki.titulares` (Google News RSS) | Titulares reales | Semillas de Noticias en modo con red |

**No se reutiliza:** el estudio Unity (queda como referencia), el VMC/XR Animator (el Studio anima los cuerpos solo) y las rutas fijas a `/home/alice` (el Studio usa `BRTV_HOME` y rutas relativas al proyecto).

## 2. Decisiones de arquitectura

1. **Un proceso nuevo, `studio/` (aiohttp, puerto 8840).** Vive al lado de `director/` sin modificarlo, así el canal en vivo no se toca. Solo *importa* funciones (`llm_con`, `voz.crear`, `cache_voz`). El puerto 8840 está libre (8780–8836 son del canal).
2. **La escena es un JSON, y la página es su render.** `/estudio` (editor) y `/salida` (1920×1080, sin interfaz) cargan el mismo `escena.js`. El servidor transmite cambios por WebSocket `/ws` (`plano`, `habla`, `expresion`, `medio`, `gc`). Lo que se ve en la vista previa es lo que graba OBS.
3. **El audio lo reproduce `/salida`.** La fuente de navegador de OBS captura el audio de la página ("controlar audio vía OBS"). El lipsync sale del mismo audio (un AnalyserNode de WebAudio) y de los tiempos por palabra cuando existen. Así voz y boca quedan sincronizadas sin cables virtuales ni VMC.
4. **Animación sin VMC.** Las poses de reposo y los gestos son procedurales (respiración, mirada a cámara o a la compañera, cabeceo al hablar, manos sobre la mesa). XR Animator o VMC quedan como entrada opcional más adelante.
5. **Personal de fondo en masa con `InstancedMesh` y siluetas low-poly** con color y orejas neko (fase 2). En el MVP habrá entre 2 y 4 extras VRM con LOD, como máximo.
6. **Generación en pasos, con checkpoint por tramo.** `programas/<id>/tramos/NN.json` se escribe al terminar cada tramo: guion, luego voz (`.wav` + tiempos), luego plan de cámaras. Si se corta la luz, el siguiente `generar` salta los tramos que ya tienen `estado: "listo"`.
7. **Reproducción determinista.** "Grabar" pone OBS en la escena del Studio, inicia la grabación y reproduce la escaleta tramo a tramo (el servidor manda los eventos y la página suena y anima). Al terminar, detiene la grabación y escribe `metadatos.json` con título, descripción y capítulos sacados de los tramos.
8. **Proveedores detrás de una interfaz.** `studio/ia.py` define `Cerebro.chat()` (local :8087 u online por clave en `.env`) y `Voz.decir()` (Piper offline, Edge si hay red, XTTS si hay GPU libre). Si falla el online, cae al local. Cada llamada suma tokens al registro del programa.
9. **Sin build.** Módulos ES nativos más el import map que ya existe. La interfaz es CSS propio con tarjetas, en estilo de juego. El i18n es un `i18n/es.json` desde el día 1, con `en` y `ja` vacíos para llenar después.
10. **Repo público.** El código nuevo no lleva IPs de LAN, rutas personales ni lore obligatorio. Blackrose es la plantilla de ejemplo en `plantillas/blackrose/`.

## 3. Estructura

```
studio/
  servidor.py        aiohttp :8840 — API REST + /ws + estáticos
  proyecto.py        cargar/guardar proyecto, validar esquema, exportar .brtv (zip)
  vrm.py             validar un .vrm subido (glTF header, versión, visemas, tamaño texturas, licencia)
  generar.py         cola de trabajos: tramos → guion → voz → cámaras (checkpoint por tramo)
  ia.py              interfaz Cerebro/Voz + proveedores local/online/manual
  obs.py             grabación vía obs-websocket
  web/
    index.html       app (5 pantallas)        /estudio
    salida.html      canvas limpio para OBS   /salida
    js/escena.js     render de la escena JSON (compartido)
    js/avatar.js     VRM + reposo + lipsync + gestos
    js/sets/noticias.js  set procedural
    i18n/es.json
studio-proyectos/<canal>/        (fuera del repo por defecto: $BRTV_HOME/proyectos)
  proyecto.json  reparto/<id>.vrm  sets/  programas/<id>/  media/  cache_voz/
```

## 4. Esquema de `proyecto.json` (v1)

```jsonc
{
  "version": 1,
  "canal": { "nombre": "Blackrose TV", "lema": "", "logo": "media/logo.png",
             "colores": { "primario": "#ff2fd6", "secundario": "#00e5ff", "fondo": "#0b0716" },
             "tipografia": "Departure Mono", "idioma": "es" },
  "ia": { "modo": "local",                      // local | online | manual
          "cerebro": { "local": "http://127.0.0.1:8087/v1", "online": { "proveedor": "", "modelo": "" } },
          "voz_defecto": "piper" },
  "reparto": [
    { "id": "joy", "nombre": "Joy", "vrm": "reparto/joy.vrm", "miniatura": "reparto/joy.png",
      "rol": "conductora",                      // conductora | panelista | reportera | invitada | fondo
      "voz": { "motor": "piper", "modelo": "es_MX-claude-high", "tono": 1.0, "velocidad": 1.0 },
      "idioma": "es", "personalidad": "Alegre, curiosa, remata con humor.", "muletillas": ["¡miau!"],
      "altura_m": 1.62, "licencia": { "uso_avatar": "OnlyAuthor", "comercial": false } }
  ],
  "programas": ["programas/2026-11-21-noticias-01"]
}
```

`programas/<id>/programa.json`:

```jsonc
{
  "id": "2026-11-21-noticias-01", "titulo": "", "formato": "noticias", "duracion_s": 180,
  "set": { "plantilla": "noticias", "ambiente": "noche",
           "luces": { "key": { "color": "#ffffff", "intensidad": 1.2 }, "fill": {}, "rim": { "color": "#ff2fd6" } },
           "camaras": [ { "id": "frontal", "tipo": "fija" }, { "id": "dos", "tipo": "fija" },
                        { "id": "grua", "tipo": "movil", "movimiento": "travelling_lento" } ],
           "posiciones": { "joy": "mesa_izq", "kuroki": "mesa_der" }, "extras": 2 },
  "tema": "", "tono": "informativo con humor", "guion_propio": null, "adjuntos": [],
  "tramos": [
    { "n": 1, "tipo": "apertura", "estado": "listo",       // pendiente | guion | voz | listo | error
      "lineas": [ { "quien": "joy", "texto": "", "audio": "tramos/01_00.wav", "dur": 4.2,
                    "plano": "frontal", "expresion": "happy", "gc": "Titular…", "medio": null } ] }
  ],
  "tokens": { "entrada": 0, "salida": 0 }
}
```

## 5. Bocetos de las 5 pantallas

```
┌ MI CANAL ───────────────────────────────┐  ┌ MI REPARTO ──────────────────────────────┐
│ [logo]  Nombre: [Blackrose TV      ]    │  │ ┌──────┐ ┌──────┐ ┌ ─ ─ ─ ┐              │
│ Colores ●●●   Tipografía [Departure ▾]  │  │ │ Joy  │ │Kuroki│ │ + VRM │ ← arrastra   │
│ Idioma [es ▾]   Modo IA (Local|Online|  │  │ │conduc│ │panel.│   aquí                │
│ Manual)         [Siguiente →]           │  │ └──────┘ └──────┘ └ ─ ─ ─ ┘              │
└─────────────────────────────────────────┘  │ [vista 3D girable] Rol▾ Voz▾ ▶probar voz │
                                             │ Personalidad [...........] ⚠ avisos VRM  │
┌ SET ────────────────────────────────────┐  └──────────────────────────────────────────┘
│ Noticias│Deportes│Panel│Entrev.│Bar│Doc  │  ┌ GUION ───────────────────────────────────┐
│ ┌──────── vista previa WebGL ────────┐  │  │ Tema [..................] Dur [3 min ▾]  │
│ │                                     │  │  │ Tono▾ Formato▾  📎 adjuntos              │
│ └─────────────────────────────────────┘  │  │ ── escaleta ──  1 Apertura   ✓ ✎ ↻      │
│ Cám: [Frontal][Dos][Grúa↝]  Luz: día/nch│  │                 2 Nota 1     ✓ ✎ ↻      │
│ Key ▮▮▮▯  Rim ● color   Extras [2]      │  │                 3 Cierre     … ✎ ↻      │
└─────────────────────────────────────────┘  └──────────────────────────────────────────┘
┌ GENERAR / GRABAR ───────────────────────────────────────────────────────────────────┐
│ [▶ Generar]  Guion ███████░░ Voz ████░░░░ Cámaras ░░░░   (reanudable)               │
│ [👁 Previsualizar]  [● Grabar con OBS]  OBS: conectado ✓  escena «STUDIO»          │
│ Salida para OBS: http://127.0.0.1:8840/salida   [copiar]                            │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## 6. Plan de la Fase 1 (MVP Noticias), en commits pequeños

1. `studio/servidor.py` sirve `/estudio` y `/salida` con un set de noticias procedural (mesa, pantalla de titulares, ventanal a la ciudad, redacción al fondo) y 3 cámaras (frontal, dos, grúa móvil). Pruebas: la página carga y el set tiene 3 planos.
2. Importar VRM: subir, validar y ver el avatar en la vista previa; las miniaturas salen del canvas. Pruebas: validador con VRM 0.x y 1.0 reales.
3. `proyecto.json` y la pantalla Mi Reparto (rol, voz, probar voz con Piper).
4. Generar: tema → 4–6 tramos → guion vía :8087 → voz Piper → plan de planos, con checkpoint. Prueba: se mata el proceso a mitad y al reanudar no se repite ningún tramo.
5. Reproducción en `/salida`: audio, lipsync, cortes de cámara, GC y titulares.
6. Grabar con OBS y escribir los metadatos. Al final, documentación corta: primeros pasos y cómo añadir un set.
