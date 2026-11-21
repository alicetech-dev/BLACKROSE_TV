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
