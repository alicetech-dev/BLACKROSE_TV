# BLACKROSE TV

Canal de TV 2049 de la Corporación Blackrose (nekos cibernéticas): director de TV autónomo, guion fractal,
estudio virtual en Unity y salida a OBS → YouTube/Twitch. Proyecto separado de `joy_vmc`.

## Contenido
| Carpeta | Qué es |
|---|---|
| `director/` | Director de TV, orquesta, productor/fractal, pensador, consola del canal (:8834), capas web |
| `ligero/` | Cerebro LLM (:8087: 4B local ⇄ 9B ThinkPad), overlay/escenario |
| `tools/` | salir_al_aire, noticiero, cliente OBS WebSocket, vigía del estudio |
| `unity/BlackroseTV/` | Proyecto Unity 2022.3.22f1 (8 sets, API :8836) — sin Library ni VRM |
| `build/` | Scripts del build (`aire.sh`, `estudio.sh`, `brtv.json`); el binario no se versiona |
| `deploy/systemd/` | Unidades de usuario (brtv-*, tv-*, cerebro, llm4b, japon-capa) |
| `tv.sh` | Comando maestro (salud, jornada, start/stop, producir…) |

## Estado de la separación
Primera copia fiel desde `joy_vmc` (2026-11-21). **`joy_vmc` sigue operando el canal**; esta copia aún no lo sustituye.
Pendiente para operar 100 % independiente:
1. Rutas `/home/alice/joy_vmc` (~350 refs en 52 archivos) → variable `BRTV_HOME`.
2. Dependencias que siguen viviendo en `joy_vmc` (dolls/VMC, `dolls.*.yaml`, voz XTTS/Piper, `.venv`).
3. Reapuntar las unidades systemd y evitar puertos duplicados al hacer el corte.

## Fuera del repo (por tamaño o privacidad)
Modelos VRM, audio/video (`director/web/tv/media`), caché de voz, logs, estado en vivo, tokens (`*.env`).

## Siguiente: Blackrose TV Studio Manager
Modo offline para crear programas (sets, luces, presentadoras, cámaras, temática) → guion/diálogo por IA → grabación en OBS.

### Studio (en construcción) — `./studio.sh start`
App web local (:8840): `/estudio` editor con vista previa WebGL, `/salida` lienzo 1920×1080 para la fuente Navegador de OBS.
Paso 1 listo: set de Noticias procedural (mesa, video wall, ventanal a la ciudad, sala de prensa con personal de fondo,
cámaras de pedestal, vara con micrófono), 4 planos (frontal, general móvil, grúa, prensa) + automático, luces y colores.
Paso 2 listo: **Mi Reparto** — arrastrar un `.vrm` (0.x/1.0), validación (esqueleto, boca, parpadeo, licencia,
peso), texturas > 2048 px achicadas (original guardado), miniatura (la del VRM o foto del navegador), vista 3D girable
y «llevar al set». CLI: `python -m studio.vrm archivo.vrm [--optimizar salida.vrm]`.
Paso 3 listo: **Estación** — prompts de la estación (sistema, directriz, uno por formato, apertura y cierre), vacíos
de fábrica y con guardado automático; IA local en secuencia (LLM → liberar VRAM → XTTS) con «Probar conexión» que solo
mira la salud (no genera ni despierta modelos); instrucción técnica fija a la vista. En Mi Reparto, ficha de **voz y
personalidad** (rol, voz XTTS con temperatura/velocidad/tono, idioma, personalidad, muletillas) y **▶ Probar voz** con
una frase que escribes tú. Todo queda en `proyecto.json` (v2). Plantilla de ejemplo: `plantillas/blackrose/`.
**App Unity (2026-11-21):** la interfaz pasa a Unity sobre los 8 sets de ESTUDIO 2049 (escena `Studio.unity`, UI Toolkit
editable en el UI Builder: `unity/BlackroseTV/Assets/BRTV/UI/`). El servidor Python queda como motor (proyecto, reparto, IA,
voz). `./studio.sh app` abre todo; compilar: menú *BlackRose TV/Studio/Compilar Linux* (build aparte del canal).
Diseño y plan: `docs/FASE0_DISENO.md`. Pruebas: `python -m pytest`.
