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
| `director/voz.py` (Piper, Edge, XTTS, ConRespaldo) | Voces intercambiables, salida float32 | Proveedor de voz del Studio (XTTS por defecto vía orquestador :9020) |
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
6. **Generación secuencial por etapas, con checkpoint por tramo.** En modo local, el LLM y XTTS nunca están cargados a la vez (6 GB de VRAM):
   - **Etapa 1, guion:** el LLM escribe todos los tramos, uno por uno. Cada tramo se guarda en `programas/<id>/tramos/NN.json` con `estado: "guion"`.
   - **Liberar:** se ejecuta el gancho `ia.local.antes_de_voz` de la estación (vacío por defecto; por ejemplo, detener el servicio del LLM) y se espera a que XTTS responda.
   - **Etapa 2, voz:** XTTS sintetiza todas las líneas (`.wav`). El tramo pasa a `estado: "voz"`.
   - **Etapa 3, cámaras:** el plan de planos es por reglas (sin GPU) y el tramo pasa a `estado: "listo"`.
   - **Corte de luz:** cada etapa salta lo que ya está hecho. Regenerar un tramo repite solo sus etapas, también en orden.
   - **XTTS es la voz por defecto.** Usa el proxy del orquestador (:9020), que lo levanta solo. Piper y Edge quedan como alternativas que se eligen a mano, nunca como cambio automático.
7. **Reproducción determinista.** "Grabar" pone OBS en la escena del Studio, inicia la grabación y reproduce la escaleta tramo a tramo (el servidor manda los eventos y la página suena y anima). Al terminar, detiene la grabación y escribe `metadatos.json` con título, descripción y capítulos sacados de los tramos.
8. **Proveedores detrás de una interfaz.** `studio/ia.py` define `Cerebro.chat()` (URL local configurable, u online con clave en `.env`) y `Voz.decir()` (XTTS por defecto). Si falla el online, cae al local. Cada llamada suma tokens al registro del programa.
8b. **Prompts vacíos, en un formulario.** El código no trae ningún texto creativo. Todo se llena en la pantalla **Estación**:
   - prompt de sistema de la estación y directriz general;
   - un prompt por formato (noticias, deportes, panel…);
   - personalidad y muletillas de cada integrante del reparto;
   - el texto de apertura y cierre.
   El repo solo trae la instrucción técnica del formato de salida (JSON de líneas), y esa se ve en el formulario pero no se edita. La plantilla Blackrose también viene con los prompts vacíos.
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
    index.html       app (6 pantallas)        /estudio
    salida.html      canvas limpio para OBS   /salida
    js/escena.js     render de la escena JSON (compartido)
    js/avatar.js     VRM + reposo + lipsync + gestos
    js/sets/noticias.js  set procedural
    i18n/es.json
studio-proyectos/<canal>/        (fuera del repo por defecto: $BRTV_HOME/proyectos)
  proyecto.json  reparto/<id>.vrm  sets/  programas/<id>/  media/  cache_voz/
```

## 4. Esquema de `proyecto.json` (v2)

Lo implementa `studio/proyecto.py` (validación, escritura atómica y migración desde v1). La ficha técnica de cada VRM
(archivo, miniatura, informe, licencia) vive en `reparto/<id>.json`; aquí solo queda lo creativo.

```jsonc
{
  "version": 2,
  "canal": { "nombre": "", "lema": "", "logo": "",           // logo: media/<archivo>.png|jpg|webp|svg
             "colores": { "primario": "#ff2fd6", "secundario": "#00e5ff", "fondo": "#0b0716" },
             "tipografia": "", "idioma": "es" },
  "estacion": {                                 // pantalla «Estación»: todo vacío de fábrica, lo llena la persona
    "prompt_sistema": "", "directriz": "",
    "formatos": { "noticias": { "prompt": "" }, "deportes": { "prompt": "" }, "panel": { "prompt": "" },
                  "entrevistas": { "prompt": "" }, "late_show": { "prompt": "" }, "documental": { "prompt": "" } },
    "apertura": "", "cierre": "" },
  "ia": { "modo": "local",                      // local | online | manual
          "secuencial": true,                   // LLM y TTS nunca a la vez
          "local": { "llm_url": "http://127.0.0.1:8087/v1/chat/completions", "modelo": "",
                     "antes_de_voz": "", "antes_de_guion": "" },   // ganchos (un comando) para liberar VRAM entre etapas
          "online": { "proveedor": "", "modelo": "" },             // la clave va en .env, nunca aquí
          "voz": { "motor": "xtts", "url": "http://127.0.0.1:9020/tts",
                   "url_salud": "" } },         // opcional: un /health que NO despierte XTTS (el proxy lo levanta con cualquier pedido)
  "reparto": {                                  // id del VRM importado → ficha creativa (se borra al quitar el VRM)
    "joy": { "rol": "",                         // "" | conductora | panelista | reportera | invitada | fondo
             "voz": { "voice": "", "temperatura": 0.75, "velocidad": 1.0, "tono": 1.0 },
             "idioma": "",                      // vacío = el del canal
             "personalidad": "", "muletillas": [] }
  },
  "programas": ["programas/2026-11-21-noticias-01"]
}
```

**Migración v1 → v2:** el `reparto` pasa de lista a objeto por id; `vrm`, `miniatura`, `altura_m` y `licencia` salen
(están en la ficha del VRM) y `voz.motor` por integrante se reemplaza por `ia.voz.motor`. Un archivo ilegible o fuera
del esquema no se pisa: queda como `proyecto.json.roto` y el Studio arranca de fábrica.

**Instrucción técnica fija** (`studio/ia.py`, `INSTRUCCION_FORMATO`): la única que trae el código; pide el JSON
`{"lineas": [{"quien", "texto", "expresion", "gc"}]}`. Se ve en Estación, no se edita.

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

## 5. Bocetos de las pantallas (Estación + 5)

```
┌ ESTACIÓN (configuración) ─────────────────────────────────────────────────────────┐
│ Prompt de sistema   [                                                       ]     │
│ Directriz general   [                                                       ]     │
│ Por formato: Noticias▸[        ] Deportes▸[        ] Panel▸[        ] …           │
│ Apertura [        ]  Cierre [        ]                                            │
│ IA: Local ● Online ○ Manual ○   LLM URL [http://127.0.0.1:8087/…]  Modelo [   ]   │
│ Secuencial ☑  Antes de voz: [comando opcional]  Antes de guion: [comando opc.]    │
│ Voz: XTTS ▾  URL [http://127.0.0.1:9020/tts]   ▸ ver instrucción técnica (fija)   │
└───────────────────────────────────────────────────────────────────────────────────┘
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
3. `proyecto.json`, pantalla **Estación** (formulario de prompts, vacíos) y Mi Reparto (rol, voz XTTS, probar voz).
4. Generar: tema → 4–6 tramos → etapa guion (LLM) → liberar VRAM → etapa voz (XTTS) → plan de planos, con checkpoint. Prueba: se mata el proceso a mitad y al reanudar no se repite ningún tramo.
5. Reproducción en `/salida`: audio, lipsync, cortes de cámara, GC y titulares.
6. Grabar con OBS y escribir los metadatos. Al final, documentación corta: primeros pasos y cómo añadir un set.
