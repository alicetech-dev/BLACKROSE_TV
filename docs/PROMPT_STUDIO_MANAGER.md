# PROMPT — Blackrose TV Studio Manager

## Rol
Eres un arquitecto/desarrollador senior de software de producción de TV virtual y de videojuegos de gestión creativa.
Vas a construir **Blackrose TV Studio Manager**: una aplicación tipo *juego creativo* donde cualquier persona
monta su propio canal de TV virtual, diseña programas con una interfaz amigable y los graba de forma offline.
Parte del código existente de este repo (`director/`, `ligero/`, `unity/BlackroseTV/`, `tools/`) y reutilízalo.

## Visión
"Un estudio de TV en tu PC, con la sencillez de un juego": eliges un set, importas a tus presentadoras (VRM),
ajustas luces y cámaras, escribes (o dictas) la temática, pulsas **Generar** y la IA produce guion, diálogo,
voces y dirección de cámaras. OBS graba el resultado para subirlo después. Sin necesidad de transmitir en vivo.

## Usuarias/os objetivo
- Creadores y VTubers sin conocimientos técnicos (principal).
- Usuarios avanzados que quieren controlar cada variable (modo manual).
- La app NO debe depender de la lore de Blackrose: Blackrose TV es el **universo por defecto / plantilla de ejemplo**;
  cada persona define el suyo (nombre del canal, marca, personajes, tono).

## Pilares de producto
1. **Amigable como un juego**: asistente de primer arranque, plantillas, vista previa en vivo, deshacer, logros/progreso
   opcionales ("primer programa", "10 programas", "set desbloqueado"), sin jerga técnica en la interfaz principal.
2. **Importar tu propio avatar**: arrastrar y soltar un `.vrm` (0.x y 1.0). Validar y avisar (tamaño, texturas, blendshapes
   visemas/expresiones, huesos, licencia VRM). Generar miniatura, asignar voz, rol y personalidad. Optimizar texturas
   automáticamente si pesan demasiado. Los modelos se quedan locales; nunca se suben a ningún servidor.
3. **Offline primero**: todo funciona sin internet en modo local; la red es opcional.
4. **Secuencial y reanudable**: pensado para una GPU de 6 GB. Cola de trabajos, un modelo a la vez, checkpoints por tramo;
   si se corta, continúa donde quedó.
5. **Transparente y editable**: la IA propone, la persona decide. Cada guion, cámara y línea es editable antes y después de generar.

## Los tres modos de IA (intercambiables por programa)
| Modo | Cerebro | Voz | Imágenes |
|---|---|---|---|
| **Online (API)** | API de LLM a elección (clave propia en ajustes) | TTS de la API o local | ComfyUI o API |
| **Local** | LLM local ~9B (llama.cpp, cuantizado) | XTTS / Piper | ComfyUI local |
| **Manual** | Todo dirigido a mano; el LLM/XTTS/Comfy son *herramientas* opcionales por botón | idem | idem |

Requisitos: abstraer el proveedor tras una interfaz única; fallback automático online→local; costo/tokens visible; claves
cifradas o en `.env`, nunca en el repo.

## Flujo de uso (el "juego")
1. **Mi Canal**: nombre, logo, colores, tipografías, ident/sting, cortinillas, música de marca (kit de identidad corporativa).
2. **Mi Reparto**: importar VRM, asignar nombre, rol (conductora, panelista, reportera, invitada, personal de fondo),
   voz, idioma, personalidad y muletillas. Soportar varios rostros (p. ej. Kuromi, Joy, Neko Gótica, Miltina como ejemplos
   de reparto) y **personal de fondo en masa** (camarógrafas, periodistas en computadores, equipo de sonido).
3. **Elegir Set**: Noticias, Deportes, Panel, Entrevistas, Talk-show/Late show en un bar con banda, Documental, Clima,
   Estelar/Show. Cada set es ajustable (ver Editor de Set).
4. **Editor de Set/Escena** (arrastrar y soltar): iluminación (key/fill/rim, color, intensidad, ambiente día/noche),
   cámaras (frontal, planos, travelling, grúa, paneo, zoom lento, cámara de fondo, cámaras que se mueven),
   ubicación de presentadoras y extras, pantallas del set (titulares, gráficos, fotos), utilería.
5. **Temática y guion**: escribir/dictar tema o pegar un guion propio; elegir tono, duración, idioma, formato
   (explicado, debate, top 3, entrevista, mito/realidad, línea de tiempo…).
6. **Material adjunto**: links, imágenes, video, PDF. Para links: abrir la página, extraer el texto y **recortar un
   screenshot** (Playwright) para usar como imagen en pantalla del set. Anexar todo al programa con su fuente.
7. **Generar**: la IA investiga (RSS/web si hay modo online o fuentes adjuntas), mejora el guion, escribe diálogos,
   genera voces, decide planos y movimientos de cámara y arma la **escaleta por tramos**. Barra de progreso por etapas.
8. **Revisar y ajustar**: línea de tiempo simple con tramos; previsualizar; regenerar solo un tramo.
9. **Grabar**: conecta a OBS (WebSocket) → escena, inicio/fin de grabación automáticos, exporta el programa y metadatos
   (título, descripción, capítulos) listos para subir.

## Tipos de programa (cada uno = plantilla + set + reglas de cámara)
- **Noticias**: prioridad. Varias cámaras del estudio (algunas móviles), plano frontal de la presentadora, cortes a
  **sala de prensa** con periodistas en computadores, camarógrafas, reporteras con vara de micrófono, un "ejército" de
  personal de fondo; titulares, GC (generador de caracteres), notas con foto/screenshot.
- **Deportes**, **Panel**, **Entrevistas**, **Late show en un bar con banda de música** (monólogo, banda, invitados).
- **Documental**: la persona da indicaciones y temas; la IA toma su script, lo **mejora, investiga**, cita fuentes y
  genera narración + imágenes/tomas de apoyo.
- **Comerciales / infomerciales, promos, cortinillas, música, reportajes**: parte de la suite de transmisión.

## Arquitectura sugerida (valida y justifica antes de codificar)
- **Render 3D (decidido: WebGL)**: Three.js + `@pixiv/three-vrm` en el navegador. **Un solo motor** para todo:
  vista previa del avatar al importar el VRM, editor de set/luces/cámaras y la **imagen de salida a OBS**.
  - Dos rutas del mismo código: `/estudio` (editor con controles) y `/salida` (canvas limpio, sin UI, resolución fija
    1920x1080, fondo transparente opcional). OBS la toma como **Browser Source**; no hace falta captura de ventana.
  - Lo que ves en la previsualización es exactamente lo que sale a OBS (misma escena, mismos planos y cámaras).
  - Escena descrita en JSON (set, luces, cámaras, reparto, props) para que el director en Python la modifique por
    WebSocket (cambio de plano, movimiento de cámara, quién habla, visemas/lipsync, expresiones, gestos).
  - Rendimiento: instancias/LOD para el personal de fondo en masa, texturas comprimidas (KTX2), límites de luces y
    sombras, perfil "bajo/medio/alto" para equipos modestos.
  - Reutiliza lo ya hecho en WebGL (`ligero/sala.py`, sala 3D, overlays web) y los sets de `unity/BlackroseTV` solo
    como **referencia de diseño** (medidas, cámaras, ambientación); Unity queda como opción heredada, no requerida.
- **Director / orquestación**: Python (reutiliza `director/`, `ligero/cerebro.py`, `fractal.py`, `instalaciones.py`).
- **Interfaz (decidido: app web)**: HTML/JS servido localmente por el director (`http://localhost:<puerto>`), sin
  Electron/Tauri en el MVP. Estilo "juego" (tarjetas, arrastrar y soltar, vista previa), responsive, sin build pesado
  (JS modular o framework ligero), comunicación por HTTP + WebSocket con el director. Un único comando de arranque
  (`./studio start`) abre el navegador. Deja la API del director limpia para que una futura versión de escritorio o
  hospedada pueda reutilizarla.
- **Persistencia**: carpeta de proyecto por canal (`proyecto.json`, `reparto/`, `sets/`, `programas/`, `media/`,
  `cache_voz/`), versionable y exportable como un solo archivo.
- **Plugins**: sets, plantillas de programa y paquetes de identidad como carpetas/JSON que otras personas puedan compartir.

## Restricciones
- Hardware objetivo: 6 GB VRAM, un solo modelo pesado a la vez; el render WebGL debe correr fluido (30–60 fps) en una iGPU
  mientras la GPU dedicada queda para LLM/XTTS/ComfyUI.
- Seguridad y legalidad: respetar licencias VRM y de medios; marcar contenido generado; sin credenciales en el repo;
  filtro de contenido configurable; no importar modelos de rutas externas sin validar.
- Los personajes pueden ser "nekos cibernéticas fabricadas por Blackrose" en el universo por defecto, pero el motor no lo exige.
- Todo texto de la interfaz en español con i18n preparado (es/en/ja).

## Entregables por fases (empieza por la 0)
0. **Auditoría y diseño**: mapa de lo reutilizable en el repo, decisiones de arquitectura, wireframes de las 5 pantallas
   (Mi Canal, Mi Reparto, Set, Guion, Generar/Grabar), esquema de `proyecto.json`. *Sin tocar producción.*
1. **MVP "Noticias"**: importar un VRM y verlo en WebGL, un set de noticias con 3 cámaras en `/salida` capturable por OBS, guion local con 9B, voz, grabación vía OBS.
2. Editor de set (luces/cámaras/extras) + personal de fondo en masa.
3. Material adjunto (links→texto+screenshot, imágenes, video).
4. Resto de formatos (deportes, panel, entrevistas, late show, documental) + modos online/manual.
5. Suite: identidad corporativa, comerciales, música, paquetes compartibles, instalador.

## Criterios de aceptación del MVP
- Una persona nueva importa su `.vrm` y obtiene un noticiero de 3 min en **menos de 15 minutos**, sin editar archivos.
- Funciona sin internet con el modo local.
- Un corte de energía a mitad de generación se reanuda sin repetir tramos ya hechos.
- Cada tramo puede regenerarse o editarse a mano.
- Documentación de usuario corta (primeros pasos) y de desarrollo (cómo añadir un set o una plantilla).

## Cómo trabajar
Responde en español. Antes de escribir código, entrega la Fase 0 y pregunta solo lo que no puedas resolver del repo.
Cambios pequeños, probados y commiteados; no rompas el canal que opera hoy desde `joy_vmc`.
