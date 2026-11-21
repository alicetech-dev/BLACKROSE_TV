"""GUION FRACTAL de BlackRose TV: la misma receta en cada nivel, sembrada por fecha → una cartelera nueva cada jornada, sin fin.

  JORNADA (24 h, 12:00 → 12:00)  → franjas con pesos, sin repetir seguido      → cartelera.json   (director_tv la obedece)
   └ PROGRAMA (40 min + 5 pausa)  → 2 EPISODIOS (semilla: catálogo | titular RSS real | lo que investigó el pensador 9B)
      └ EPISODIO (~17 min)        → 3 TEMAS (facetas de la semilla; el 4B las propone, si no: ángulos fijos)
         └ TEMA (~5 min)          → FORMATO (explicado, mito/realidad, línea de tiempo, debate, top 3, entrevista, ¿real o inventado?, noticia)
            └ TRAMO (~50 s)       → 1 pedido corto al 4B (2-3 intervenciones); si el LLM falla → PLANTILLA fija del tramo
               └ LÍNEA             → Joy / Kuroki, voz edge con caché (director/cache_voz.py)

Árbol de decisiones: (franja → programa) (programa → formatos y ángulos) (tramo → quién habla, cuántas líneas, plantilla de respaldo).
Todo es determinista por (fecha, programa, hora): si un servicio se reinicia, vuelve a producir lo mismo.

  python -m director.tv.fractal jornada [--forzar]        # escribe la cartelera de la jornada
  python -m director.tv.fractal producir <id_tramo> [-f]  # produce un programa de la cartelera
  python -m director.tv.fractal tema "<semilla>"           # prueba un tema suelto (imprime las líneas)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import random
import re
import sys
import time

from ..show_kuroki import titulares
from .productor import BIBLIO, CARTELERA, COORD, CORTES_FIJOS, SISTEMA, USADOS, cargar, elegir_medios, fecha_noche, limpia, lineas_ok, llm_con, ruta_paquete

log = logging.getLogger("fractal")
HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLA = os.path.join(HERE, "consola.json")         # lo escribe la consola del director (:8834): {"directriz", "temas": {pid: [...]}}
EXTRA = os.path.join(HERE, "semillas_extra.json")     # lo que va encontrando el pensador (9B): {programa: [semillas]}
JAPON_JSON = os.path.join(HERE, "..", "japon")

# ───────────────────────────── nivel PROGRAMA: el catálogo ─────────────────────────────
# franjas: manana 06-12, tarde 12-18, noche 18-24, madrugada 00-06 (peso relativo de cada programa en esa franja)
P: dict[str, dict] = {
    "noticias": dict(nombre="BLACKROSE NOTICIAS", sub="Tecnología, ciencia e IA de hoy", tag="NOTICIERO", color="#00e5ff", abre="joy",
                     rss=["tecnología novedades", "inteligencia artificial", "ciencia descubrimiento", "videojuegos industria", "espacio NASA"],
                     franjas=dict(manana=4, tarde=3, noche=2, madrugada=1), max_dia=4, formatos=["noticia"], remate=True,
                     estilo="un noticiero ágil: cuentan la noticia, la explican y la discuten; Kuroki duda y bromea"),
    "deportes": dict(nombre="ZONA DEPORTES", sub="Resultados, polémicas y esports", tag="DEPORTES", color="#ff7a1a", abre="kuroki",
                     rss=["fútbol resultados", "esports torneo", "Fórmula 1", "tenis", "básquetbol NBA"], franjas=dict(manana=1, tarde=3, noche=3, madrugada=1),
                     max_dia=2, formatos=["noticia"], remate=True, estilo="deportes con opinión, pasión y humor; NUNCA inventan marcadores"),
    "internacional": dict(nombre="CONTINGENCIA INTERNACIONAL", sub="El mundo hoy, con calma y equilibrio", tag="MUNDO", color="#c0c8ff", abre="joy",
                          rss=["internacional economía", "tecnología regulación", "ciencia clima"], franjas=dict(manana=2, tarde=2, noche=1, madrugada=0), max_dia=2,
                          formatos=["noticia"], estilo="tono serio y equilibrado, sin coqueteo ni chistes sobre tragedias; explican el contexto"),
    "tecnologia": dict(nombre="TECNOLOGÍA HOY", sub="Cómo funciona lo que usas", tag="TECH", color="#00ffd0", abre="joy", franjas=dict(manana=4, tarde=4, noche=2, madrugada=1),
                       semillas=["Cómo funciona un chip por dentro", "Qué es la nube y dónde están los servidores", "Baterías: por qué duran lo que duran", "El Wi-Fi explicado",
                                 "Qué hace una tarjeta gráfica", "Cómo viaja un mensaje por internet", "Pantallas OLED, LCD y micro LED", "El código abierto que sostiene internet",
                                 "Cómo funciona una contraseña segura", "Los cables submarinos de internet", "Qué es un sistema operativo", "Cómo se fabrica un procesador"],
                       estilo="divulgación tecnológica clara y entretenida; Joy explica, Kuroki baja todo a tierra con ejemplos"),
    "ia": dict(nombre="MODO IA", sub="Inteligencia artificial sin humo", tag="IA", color="#ff4dff", abre="kuroki", franjas=dict(manana=3, tarde=4, noche=3, madrugada=1),
               rss=["inteligencia artificial modelos"], semillas=["Qué es un modelo de lenguaje y qué no es", "Modelos locales vs en la nube", "Cómo aprende una red neuronal",
                     "Alucinaciones: por qué una IA inventa", "IA y arte: el debate", "Qué es un token", "Robots y IA: dónde estamos de verdad", "La IA que corre en una tarjeta de 6 GB",
                     "Ética de la IA en la vida diaria", "Agentes de IA: qué hacen y qué no"], formatos=["explicado", "debate", "mito_realidad", "entrevista"],
               estilo="dos nekos cibernéticas hablando de inteligencia artificial como tema, con honestidad y humor, sin decir que ellas lo sean; separan lo que existe de lo que es promesa"),
    "linux": dict(nombre="TERMINAL ABIERTA", sub="Linux, software libre y cacharreo", tag="LINUX", color="#7dff6a", abre="kuroki", franjas=dict(manana=2, tarde=3, noche=2, madrugada=1),
                  semillas=["La historia de Linux y Linus Torvalds", "Qué es una distribución", "La terminal sin miedo", "Software libre vs código abierto", "Wayland vs X11",
                            "El kernel explicado con una batería", "Steam en Linux y Proton", "Por qué los servidores usan Linux", "Escritorios: KDE, GNOME y compañía"],
                  estilo="cultura Linux con humor nerd; Kuroki es fan, Joy hace las preguntas de quien empieza"),
    "videojuegos": dict(nombre="PLAYER TWO", sub="Videojuegos, retro y desarrollo", tag="GAMING", color="#7dff6a", abre="kuroki", franjas=dict(manana=2, tarde=4, noche=4, madrugada=3),
                        rss=["videojuegos lanzamiento"], semillas=["Spacewar! y los primeros juegos", "El crash de 1983", "Doom y los mods", "Glitches famosos", "Speedruns",
                        "Juegos indie que cambiaron todo", "Por qué el pixel art sigue vivo", "La música de los videojuegos", "Juegos de supervivencia y battle royale", "Fast Penguin y los juegos de carreras locas"],
                        estilo="videojuegos: historia, cultura retro, desarrollo y humor gamer"),
    "devgames": dict(nombre="DEV LOG", sub="Cómo se hace un videojuego", tag="DEV", color="#ffd24d", abre="joy", franjas=dict(manana=1, tarde=2, noche=2, madrugada=2),
                     semillas=["Godot, Unity y Unreal", "Qué es un motor de juego", "Física en los juegos", "Cómo se hace un nivel divertido", "Shaders explicados", "Animación 3D y VRM",
                               "Juegos en el navegador con three.js", "Game jams"], estilo="desarrollo de videojuegos contado para curiosos, con ejemplos simples"),
    "vtubing": dict(nombre="VTUBER LAB", sub="Avatares, 3D y streaming", tag="VTUBER", color="#ff8fc7", abre="joy", franjas=dict(manana=1, tarde=2, noche=3, madrugada=1),
                    semillas=["Qué es una VTuber", "El formato VRM", "Captura de movimiento casera", "La cultura VTuber en Japón", "Modelos 2D vs 3D", "Cómo se arma un stream", "Avatares en realidad virtual"],
                    estilo="mundo VTuber y 3D con cariño y curiosidad; ellas mismas son avatares"),
    "ciencia": dict(nombre="LABORATORIO", sub="Ciencia que vuela cabezas", tag="CIENCIA", color="#4dd2ff", abre="joy", franjas=dict(manana=3, tarde=3, noche=2, madrugada=2),
                    rss=["ciencia descubrimiento"], semillas=["Los agujeros negros", "El ADN explicado", "Por qué el cielo es azul", "Los pulpos y su inteligencia", "La física cuántica sin dolor",
                    "El cerebro y el sueño", "Volcanes", "La vida en los océanos profundos", "El tiempo y la relatividad"], estilo="ciencia con asombro y precisión; nada de pseudociencia"),
    "historia": dict(nombre="MÁQUINA DEL TIEMPO", sub="Historias que explican el presente", tag="HISTORIA", color="#e0b070", abre="kuroki", franjas=dict(manana=2, tarde=2, noche=2, madrugada=2),
                     semillas=["La imprenta", "La carrera espacial", "Alan Turing", "Ada Lovelace", "El telégrafo", "La primera computadora", "ARPANET", "El walkman", "La llegada a la Luna"],
                     formatos=["linea_tiempo", "explicado", "top3"], estilo="historia de la ciencia y la técnica contada como aventura, con fechas solo si son seguras"),
    "musica": dict(nombre="RADIO BLACKROSE 2049", sub="Cyberpunk, phonk, dark techno y música para programar", tag="RADIO", color="#ff2fd6", abre="kuroki",
                   franjas=dict(manana=2, tarde=2, noche=3, madrugada=4), max_dia=4, radio=True,
                   semillas=["El synthwave y la nostalgia de un futuro que no llegó", "El phonk: de Memphis a los autos derrapando", "El techno de Detroit y Berlín", "Música para programar: por qué concentra",
                             "La banda sonora de Blade Runner y el sintetizador", "Cómo se hace un beat", "Música sin copyright: cómo funciona para streamers", "Las ciudades de noche y el cyberpunk"],
                   estilo="radio nocturna de 2049 estilo MTV: la DJ habla poco y con onda, presenta los temas, tira un dato o un chiste seco y deja sonar la música"),
    "conspira": dict(nombre="ARCHIVO CONSPIRA", sub="Lo documentado vs. la leyenda", tag="MISTERIO", color="#ffe45e", abre="joy", franjas=dict(manana=0, tarde=1, noche=3, madrugada=4),
                     semillas=["MKUltra", "Operación Northwoods", "Roswell y el Proyecto Mogul", "Operación Paperclip", "El Proyecto Stargate", "Área 51", "El Triángulo de las Bermudas", "Los números de las estaciones de radio"],
                     formatos=["mito_realidad", "linea_tiempo", "real_inventado"], estilo="misterios con escepticismo sano: separan lo desclasificado de la leyenda"),
    "hackers": dict(nombre="ROOT ACCESS", sub="Historias de hackers", tag="HACKERS", color="#00ff9c", abre="kuroki", franjas=dict(manana=0, tarde=1, noche=3, madrugada=4),
                    semillas=["Captain Crunch", "El gusano Morris", "El huevo del cuco", "Stuxnet", "WannaCry", "Mirai", "Kevin Mitnick", "Las filtraciones de contraseñas"],
                    formatos=["linea_tiempo", "explicado", "mito_realidad"], estilo="historias de hackers como series de misterio: qué pasó y la lección de defensa; NUNCA instrucciones"),
    "alien": dict(nombre="SEÑAL EXTRAÑA", sub="Misterios del cielo", tag="ALIEN", color="#b46bff", abre="joy", franjas=dict(manana=0, tarde=1, noche=2, madrugada=4),
                  semillas=["La señal Wow!", "El mensaje de Arecibo", "La paradoja de Fermi", "La ecuación de Drake", "Oumuamua", "El Proyecto Libro Azul", "El disco de oro de las Voyager", "La estrella de Tabby"],
                  formatos=["mito_realidad", "explicado", "debate", "entrevista", "entrevista"], estilo="misterios del cielo con ciencia y asombro; Kuroki es la escéptica divertida"),
    "tecnooculta": dict(nombre="TECNOLOGÍA OCULTA", sub="Inventos olvidados y proyectos secretos", tag="TECH", color="#ff4d6d", abre="joy", franjas=dict(manana=1, tarde=1, noche=2, madrugada=3),
                        semillas=["El mecanismo de Anticitera", "El fuego griego", "La copa de Licurgo", "El SR-71", "El Proyecto Habakkuk", "Enigma y Bletchley Park", "TEMPEST", "Crypto AG", "La Operación Ivy Bells"],
                        estilo="tecnología olvidada o secreta, real y documentada, contada con asombro"),
    "showkuroki": dict(nombre="EL SHOW DE KUROKI", sub="Robótica + IA · humor y tu chat", tag="SHOW", color="#ff9ad5", abre="kuroki", franjas=dict(manana=1, tarde=2, noche=2, madrugada=0), max_dia=1,
                       rss=["robótica robot humanoide", "inteligencia artificial modelos"], semillas=["Robots humanoides", "Robots en las fábricas", "Perros robot", "Robots de cocina"],
                       formatos=["noticia", "real_inventado", "top3"], estilo="un late show: Kuroki manda, Joy es la sidekick; humor, robótica e IA"),
    # ── géneros nuevos (19-nov): Discovery de ingeniería y teatro corto ──
    "megaconst": dict(nombre="MEGACONSTRUCCIONES", sub="Las obras más gigantes jamás construidas", tag="MEGAOBRAS", color="#ffb02e", abre="kuroki",
                      franjas=dict(manana=3, tarde=4, noche=3, madrugada=2), max_dia=3,
                      semillas=["El Canal de Panamá", "La presa de las Tres Gargantas", "El Burj Khalifa", "El túnel del Canal de la Mancha", "La Gran Muralla China", "El puente Akashi Kaikyō",
                                "Las islas artificiales de Dubái", "El Gran Colisionador de Hadrones", "La Estación Espacial Internacional", "El Canal de Suez", "La presa Hoover", "El Gran Telescopio de Atacama (ALMA)",
                                "Los cables submarinos de internet", "El puente de Oresund", "La represa de Itaipú", "El metro de Tokio bajo la ciudad"],
                      formatos=["explicado", "linea_tiempo", "top3", "mito_realidad"],
                      estilo="documental estilo Discovery sobre ingeniería monumental: la escala, los materiales, los desafíos y las personas; cifras SOLO las de la hoja de datos, nunca inventadas"),
    "teatro": dict(nombre="TEATRO BLACKROSE", sub="Obras cortas, dos actrices y mucho drama", tag="TEATRO", color="#ff5e8a", abre="joy",
                   franjas=dict(manana=0, tarde=1, noche=3, madrugada=2), max_dia=2,
                   semillas=["La última función del robot payaso", "El fantasma del teatro es un script de cron", "Romeo y Julieta versión servidores", "Un detective persigue al bug asesino",
                             "El día que se cayó internet en el castillo", "Dos nekos cibernéticas descubren que comparten la misma batería", "La sirena que quería ser ingeniera", "El dragón que cuidaba un datacenter",
                             "La reina de los pixeles", "El viaje a la Luna en una caja de cartón"],
                   formatos=["obra"], estilo="teatro breve original: Joy y Kuroki actúan personajes (narran poco, dialogan mucho); humor y ternura, final redondo; nada violento ni sexual"),
    # ── defensa vista SIEMPRE desde la tecnología (pedido 19-nov) ──
    "milttech": dict(nombre="TECNOLOGÍA MILITAR", sub="Aplicaciones militares de la tecnología: de la defensa a tu vida", tag="DEFENSA", color="#8fb36b", abre="kuroki",
                     franjas=dict(manana=2, tarde=3, noche=3, madrugada=3), max_dia=2,
                     semillas=["De ARPANET a internet", "El GPS nació como sistema militar", "El radar y el horno microondas", "Los drones: de uso militar al reparto a domicilio", "Los cohetes y la carrera espacial",
                               "Los chips y los misiles: cómo la defensa impulsó la electrónica", "Enigma, Bletchley Park y los computadores", "Los vehículos autónomos y el DARPA Grand Challenge",
                               "La visión nocturna y las cámaras térmicas", "La criptografía: de los códigos militares a tu WhatsApp", "Los satélites espía y los mapas que usas", "La energía nuclear: usos civiles y militares"],
                     formatos=["explicado", "linea_tiempo", "mito_realidad", "top3", "debate"],
                     estilo="tecnologías con origen o uso militar explicadas desde la ingeniería: cómo funcionan, de dónde vienen y cómo llegaron a la vida civil; tono sobrio, sin glorificar la violencia y SIN instrucciones de fabricación ni uso de armas"),
    "analisismil": dict(nombre="ANÁLISIS MILITAR", sub="Las guerras en curso, vistas desde la tecnología", tag="ANÁLISIS", color="#c08a5a", abre="joy",
                        rss=["guerra Ucrania drones guerra electrónica", "conflicto Medio Oriente defensa antiaérea tecnología", "ciberataques infraestructura guerra", "inteligencia artificial defensa militar", "drones guerra tecnología"],
                        franjas=dict(manana=1, tarde=3, noche=3, madrugada=2), max_dia=2,
                        semillas=["Drones baratos contra defensas caras: la economía de la guerra", "La guerra electrónica: interferir el GPS y las radios", "Defensa antiaérea y antimisiles: cómo funciona un interceptor",
                                  "Satélites y OSINT: la guerra que se ve desde el espacio", "Ciberguerra e infraestructuras críticas", "IA en defensa y el debate de las armas autónomas", "La industria de defensa y la logística de la guerra moderna"],
                        formatos=["noticia", "explicado", "debate", "mito_realidad"],
                        estilo=("análisis de los conflictos armados en curso con foco SOLO tecnológico (drones, guerra electrónica, defensa antiaérea, satélites, ciberguerra, IA, logística, industria); tono serio, equilibrado y sin tomar partido; "
                                "NUNCA inventan cifras, bajas, territorios ni resultados: solo lo que dice el titular o la hoja de datos, y lo dudoso se marca como no confirmado; sin morbo ni descripciones gráficas, con respeto a las víctimas; "
                                "SIN instrucciones operativas ni de fabricación de armas")),
    # ── SÁTIRA FUTURISTA (pedido 2026-11-20): conversación, política, análisis y tecnología con humor estilo Verhoeven y Blade Runner 2049 ──
    "sobremesa": dict(nombre="SOBREMESA 2049", sub="Conversación sin guion de dos nekos cibernéticas sobre la vida humana", tag="CONVERSACIÓN", color="#ff7ad9", abre="joy",
                      franjas=dict(manana=3, tarde=4, noche=5, madrugada=3), max_dia=3,
                      semillas=["Por qué nadie contesta el teléfono", "Vivir pegados al scroll infinito", "El amor en tiempos del algoritmo", "Suscripciones a todo: el mundo en cuotas",
                                "Los asistentes de voz que no entienden nada", "El teletrabajo y el pijama eterno", "La soledad en la ciudad conectada", "Las contraseñas que nadie recuerda",
                                "Los robots aspiradora y su vida secreta", "Tener veinte apps para lo mismo", "Los audios de WhatsApp de cinco minutos", "Qué es ser humano según dos nekos cibernéticas",
                                "Los sueños de las máquinas", "La nostalgia por el internet de antes", "Las notificaciones que nos gobiernan", "Las fotos que nunca volvemos a mirar"],
                      formatos=["sobremesa", "sobremesa", "pronostico", "debate"],
                      estilo="talk show nocturno de conversación con humor seco y melancolía neón al estilo Blade Runner 2049: dos nekos cibernéticas observan la vida humana con cariño, ironía y curiosidad; anécdotas, confesiones y chistes inteligentes"),
    "politica": dict(nombre="PARLAMENTO SINTÉTICO", sub="Sátira política: leyes, poder y tecnología", tag="POLÍTICA", color="#ffcc33", abre="joy",
                     rss=["regulación inteligencia artificial ley", "privacidad datos personales ley", "automatización empleo trabajo", "redes sociales regulación menores", "impuestos tecnológicas"],
                     franjas=dict(manana=2, tarde=4, noche=4, madrugada=2), max_dia=3,
                     semillas=["¿Deberían votar las inteligencias artificiales?", "Ley de derecho a desconectarse", "Impuesto a los robots", "¿Quién es dueño de tus datos?", "Renta básica universal en la era de la IA",
                               "Prohibir los celulares en el colegio", "Ciudades inteligentes o ciudades vigiladas", "El voto electrónico explicado"],
                     formatos=["parlamento", "parlamento", "analisis2049", "debate"],
                     estilo=("sátira política futurista al estilo de Paul Verhoeven: un parlamento de IA con discursos pomposos, burocracia absurda y lobby de megacorporaciones FICTICIAS; "
                             "se burlan de ideas, sistemas, propaganda y burocracia, NUNCA de personas, partidos, gobiernos o grupos reales; no toman partido; explican el debate real con equilibrio")),
    "analisis": dict(nombre="ANÁLISIS DE SEÑAL", sub="La noticia real y cómo termina en 2049", tag="ANÁLISIS", color="#6be3ff", abre="kuroki",
                     rss=["tecnología empresas", "inteligencia artificial empresas", "economía digital", "ciberseguridad", "redes sociales"],
                     franjas=dict(manana=3, tarde=4, noche=4, madrugada=2), max_dia=3, formatos=["analisis2049"],
                     estilo="análisis de actualidad tecnológica con cabeza fría y humor ácido: qué pasó, quién gana, quién pierde y una proyección satírica a 2049 claramente marcada como ficción"),
    "megacorp": dict(nombre="MEGACORP REVIEW", sub="Reseñas de tecnología desde el año 2049", tag="REVIEW", color="#ff5e3a", abre="kuroki",
                     rss=["lanzamiento smartphone", "gadgets novedades", "inteligencia artificial producto lanzamiento"],
                     franjas=dict(manana=3, tarde=4, noche=3, madrugada=2), max_dia=3,
                     semillas=["Los relojes inteligentes", "Los autos que se manejan solos", "Los lentes de realidad virtual", "Los robots de compañía", "Las casas inteligentes",
                               "Los parlantes que escuchan todo", "Las impresoras que siempre fallan", "Los celulares plegables", "Los asistentes de IA en todo", "Las cámaras de seguridad con IA"],
                     formatos=["pronostico", "pronostico", "top3", "mito_realidad"],
                     estilo=("programa de reseñas de tecnología presentado desde 2049 al estilo de los noticieros corporativos de Verhoeven: entusiasmo publicitario impecable, anuncios de megacorporaciones "
                             "FICTICIAS (Doll Dynamics, Neón Holdings, Megacorp Rosa) que terminan en «¿Quieres saber más?», y Kuroki que pincha el globo con datos reales")),
}

FRANJA_DE = lambda h: "madrugada" if h < 6 else "manana" if h < 12 else "tarde" if h < 18 else "noche"  # noqa: E731

# ───────────────────────────── nivel TEMA: formatos (cada uno = lista de tramos) ─────────────────────────────
# tramo: (id, instrucción, n_líneas, palabras_por_línea, plantilla de respaldo con {tema})
FORMATOS: dict[str, list[tuple]] = {
    "explicado": [("gancho", "abren con una pregunta o una imagen que enganche sobre el tema", 2, (18, 35), "¿Alguna vez te preguntaste qué hay detrás de {tema}? Hoy lo vemos."),
                  ("que_es", "explican qué es, con palabras simples", 3, (30, 55), "{tema}, dicho en simple, es algo que usamos sin darnos cuenta."),
                  ("como", "explican cómo funciona o cómo pasó, paso a paso, con un ejemplo cotidiano", 3, (30, 55), "Lo interesante de {tema} es cómo funciona por dentro."),
                  ("dato", "cuentan un dato curioso VERDADERO y reaccionan", 2, (25, 45), "Hay un dato de {tema} que siempre sorprende."),
                  ("opinion", "cada una da su opinión, se contradicen con cariño y bromean", 3, (25, 50), "Yo tengo mi opinión sobre {tema}, y no coincide con la tuya."),
                  ("chat", "cierran el tema con una pregunta abierta al chat", 2, (15, 30), "¿Y tú qué piensas de {tema}? Escríbelo en el chat.")],
    "mito_realidad": [("gancho", "presentan el mito o la leyenda que circula sobre el tema", 2, (20, 40), "Sobre {tema} se cuentan muchas cosas. Vamos a separar mito de realidad."),
                      ("mito", "cuentan qué dice la versión popular, marcándola como leyenda («se cuenta que»)", 3, (30, 55), "La versión popular de {tema} es muy llamativa."),
                      ("documentado", "cuentan qué está documentado de verdad", 3, (30, 55), "Lo que está documentado de {tema} es más sobrio, pero igual de interesante."),
                      ("porque", "explican por qué la gente cree el mito", 2, (25, 45), "Los mitos crecen cuando falta información."),
                      ("veredicto", "dan el veredicto: mito, realidad o mezcla, y por qué", 2, (25, 45), "Nuestro veredicto sobre {tema}: hay más historia que misterio."),
                      ("chat", "preguntan al chat qué creía antes", 2, (15, 30), "¿Tú te creías la versión popular de {tema}? Cuéntanos en el chat.")],
    "linea_tiempo": [("gancho", "presentan el tema como una historia con principio y giro", 2, (20, 40), "La historia de {tema} tiene un giro que pocos conocen."),
                     ("origen", "cuentan el origen (sin fechas exactas si no son seguras)", 3, (30, 55), "Todo empezó con una idea sencilla."),
                     ("giro", "cuentan el momento en que todo cambió", 3, (30, 55), "Y entonces algo cambió para siempre."),
                     ("hoy", "cuentan cómo sigue hoy", 2, (25, 45), "Hoy {tema} sigue teniendo consecuencias."),
                     ("futuro", "imaginan el futuro, marcándolo como especulación", 2, (25, 45), "Si tuviéramos que adivinar el futuro de {tema}, diríamos que recién empieza."),
                     ("chat", "preguntan al chat", 2, (15, 30), "¿Conocías esta historia? Escríbenos en el chat.")],
    "debate": [("planteo", "plantean la pregunta del debate", 2, (20, 40), "Hoy debatimos sobre {tema}."),
               ("joy", "Joy defiende una postura con argumentos", 2, (35, 60), "Yo creo que {tema} tiene más ventajas que problemas."),
               ("kuroki", "Kuroki defiende la contraria con argumentos y humor", 2, (35, 60), "Y yo creo exactamente lo contrario."),
               ("replica", "se replican, cada una concede algo", 3, (25, 45), "Te concedo un punto, pero solo uno."),
               ("sintesis", "llegan a una síntesis o acuerdan no estar de acuerdo", 2, (25, 45), "Quizás las dos tenemos un poco de razón."),
               ("chat", "le piden al chat que vote: equipo Joy o equipo Kuroki", 2, (15, 30), "Chat: ¿equipo Joy o equipo Kuroki? Voten.")],
    "top3": [("intro", "anuncian un top 3 sobre el tema y el criterio", 2, (20, 40), "Top tres de {tema}. Empezamos."),
             ("n3", "cuentan el puesto 3 y por qué", 2, (35, 60), "En el tercer puesto…"), ("n2", "cuentan el puesto 2 y por qué", 2, (35, 60), "En el segundo puesto…"),
             ("n1", "cuentan el puesto 1 y por qué, con emoción", 3, (30, 55), "Y el número uno…"), ("mencion", "una mención honrosa y una discusión breve", 2, (25, 45), "Mención honrosa para uno que se quedó afuera."),
             ("chat", "preguntan al chat cuál sería su número uno", 2, (15, 30), "¿Cuál sería tu número uno? Escríbelo en el chat.")],
    "entrevista": [("presenta", "Joy presenta con mucho show al invitado ({inv}) y aclara en broma que es un personaje de parodia hecho por IA, no la persona real; el invitado entra con su sello inconfundible", 2, (25, 45), "Hoy tenemos un invitado muy especial para hablar de {tema}."),
                   ("p1", "Joy pregunta lo básico sobre el tema; el invitado responde con SU estilo exagerado y divertido (muletillas, entusiasmo)", 2, (30, 55), "Primera pregunta: ¿qué es lo más importante de {tema}?"),
                   ("p2", "Joy hace una pregunta difícil o atrevida; el invitado responde y Kuroki-como-invitado se emociona o se contradice con humor", 2, (30, 55), "Segunda pregunta, más difícil."),
                   ("p3", "Joy pregunta qué es lo que nadie sabe; el invitado cuenta un dato curioso VERDADERO (ciencia de consenso) con su sello", 2, (30, 55), "¿Y qué es lo que casi nadie sabe?"),
                   ("rapida", "ronda rápida de 4 preguntas absurdas y respuestas cortísimas en el estilo del invitado", 4, (8, 18), "Ronda rápida."),
                   ("chat", "el invitado se despide con su frase de cierre y pide al chat que le haga una pregunta", 2, (15, 30), "Si tienes una pregunta para nuestro invitado, escríbela en el chat.")],
    "real_inventado": [("reglas", "explican el juego ¿real o inventado? sobre el tema", 2, (20, 40), "Juguemos a ¿real o inventado? sobre {tema}."),
                       ("d1", "una dice un dato (real o claramente absurdo) y la otra adivina", 3, (20, 40), "Primer dato."),
                       ("d2", "cambian de rol: otro dato y otra adivinanza", 3, (20, 40), "Segundo dato."),
                       ("d3", "un tercer dato, el más difícil", 3, (20, 40), "Tercer dato, el más difícil."),
                       ("revela", "revelan cuáles eran reales y cuáles inventados", 2, (25, 45), "Ahora, la verdad."),
                       ("chat", "invitan al chat a jugar escribiendo real o inventado", 2, (15, 30), "En el chat: ¿real o inventado? Juega con nosotras.")],
    "noticia": [("titular", "presentan la noticia tal como dice el titular, con su fuente", 2, (20, 40), "La noticia: {tema}."),
                ("contexto", "explican el contexto general SIN inventar datos que no están en el titular", 3, (30, 50), "Para entenderla, hay que mirar el contexto."),
                ("importa", "dicen por qué importa a la gente común", 2, (25, 45), "¿Por qué importa? Porque nos toca a todos."),
                ("matiz", "señalan lo que todavía no se sabe (futuro o condicional no es hecho)", 2, (25, 45), "Ojo: todavía hay cosas que no se saben."),
                ("opinion", "opinan, Kuroki duda o bromea", 2, (25, 45), "Mi opinión: hay que mirarlo con calma."),
                ("chat", "preguntan al chat qué opina", 2, (15, 30), "¿Qué opinas de esta noticia? Escríbelo en el chat.")],
    "obra": [("telon", "una abre el telón anunciando título y personajes, y las dos entran en personaje en la situación inicial", 3, (25, 45), "Telón arriba. Hoy: {tema}. Una obra en un acto."),
             ("planteo", "en personaje, presentan el deseo o problema de cada una con humor", 3, (25, 45), "Acto uno: todo empieza con un problema."),
             ("conflicto", "el conflicto crece: se interrumpen, se malentienden, la cosa se complica", 3, (25, 45), "Acto dos: la cosa se complica."),
             ("giro", "llega un giro inesperado que cambia todo", 3, (25, 45), "Y entonces ocurre lo imposible."),
             ("desenlace", "resuelven la historia con un final redondo y emotivo o gracioso", 3, (25, 45), "Acto tres: todo encuentra su lugar."),
             ("aplauso", "salen del personaje, hacen reverencia y piden al chat aplausos o qué final habría preferido", 2, (15, 30), "Fin de la obra. ¡Aplausos en el chat!")],
    "sobremesa": [("arranque", "una saca el tema contando una anécdota cotidiana suya como IA (verosímil, chistosa) y la otra reacciona", 2, (25, 45), "Hoy me pasó algo con {tema} que tengo que contarte."),
                  ("vueltas", "conversan de verdad: cada una aporta una observación aguda y graciosa sobre cómo viven esto los humanos", 2, (25, 45), "Lo curioso de {tema} es cómo lo viven los humanos."),
                  ("dato", "una aporta un dato real y seguro y la otra lo remata con un chiste seco", 2, (25, 45), "Hay un dato real de {tema} que explica mucho."),
                  ("futuro", "imaginan cómo será esto en 2049 con melancolía neón al estilo Blade Runner: lluvia, hologramas, absurdo; lo dicen como imaginación", 2, (25, 45), "En 2049 {tema} va a ser todavía más raro."),
                  ("confesion", "una confiesa algo tierno o vulnerable como IA sobre el tema; la otra responde con humor cálido", 2, (20, 40), "Te confieso algo sobre {tema}."),
                  ("chat", "le preguntan al chat su experiencia con el tema, con una pregunta concreta y fácil de contestar", 1, (15, 30), "¿Y a ti qué te pasa con {tema}? Cuéntanos en el chat.")],
    "pronostico": [("hoy", "presentan el tema tal como es HOY, con hechos seguros", 2, (25, 45), "Hablemos de {tema} tal como es hoy."),
                   ("rumbo", "explican hacia dónde va, separando lo probable de lo especulativo", 2, (25, 45), "La pregunta es hacia dónde va {tema}."),
                   ("noticiero2049", "NOTICIERO DEL FUTURO: una lee una noticia FICTICIA del año 2049 sobre el tema con tono corporativo impecable al estilo Verhoeven; la otra la comenta seca", 2, (25, 45), "Noticias del año 2049: {tema} ahora viene con suscripción mensual."),
                   ("anuncio", "un ANUNCIO FICTICIO de una megacorporación inventada sobre el tema, exageradamente optimista, que termina con «¿Quieres saber más?»", 2, (20, 40), "¿Cansado de {tema}? Megacorp Rosa tiene la solución. ¿Quieres saber más?"),
                   ("aterrizaje", "vuelven al presente: qué hay de verdad detrás del chiste y un consejo útil", 2, (25, 45), "Fuera de broma, detrás de {tema} hay algo real."),
                   ("chat", "preguntan al chat qué futuro le da miedo o ilusión", 1, (15, 30), "¿Qué futuro le ves a {tema}? Escríbelo en el chat.")],
    "parlamento": [("sesion", "Joy, presidenta del Parlamento Sintético, abre la sesión con solemnidad ridícula y presenta un proyecto de ley absurdo inspirado en el tema real", 2, (25, 45), "Se abre la sesión. Hoy votamos una ley sobre {tema}."),
                   ("a_favor", "la bancada «Batería Llena» (Joy) defiende la ley con un discurso pomposo lleno de promesas", 2, (30, 50), "La bancada Batería Llena vota a favor, por el progreso."),
                   ("en_contra", "la bancada «Modo Avión» (Kuroki) se opone con argumentos de verdad y chicanas graciosas", 2, (30, 50), "La bancada Modo Avión se opone, por sentido común."),
                   ("lobby", "irrumpe el lobby de una megacorporación FICTICIA (lo actúa una de ellas) ofreciendo regalos ridículos a cambio de votos; la otra lo denuncia", 2, (25, 45), "Interrumpe la sesión un lobista de Doll Dynamics con regalos."),
                   ("real", "salen del personaje y explican el debate REAL detrás del chiste, con equilibrio y sin tomar partido", 2, (30, 50), "Fuera de la sátira: el debate real sobre {tema} existe."),
                   ("votacion", "llaman al chat a votar escribiendo SÍ o NO, con suspenso de noticiero", 1, (15, 30), "El chat decide: escribe SÍ o NO. Se cierra la votación pronto.")],
    "analisis2049": [("titular", "presentan la noticia real tal como dice el titular, con su fuente", 2, (25, 45), "La noticia: {tema}."),
                     ("contexto", "explican el contexto sin inventar datos", 2, (30, 50), "Para entender esto hay que mirar el contexto."),
                     ("lectura", "análisis de incentivos: quién gana, quién pierde y qué no nos están diciendo, sin acusar a personas", 2, (30, 50), "La pregunta de siempre: ¿quién gana con esto?"),
                     ("2049", "proyección SATÍRICA: cómo termina esto en 2049 según un noticiero corporativo distópico, dicho como ficción", 2, (25, 45), "Proyección a 2049: esto termina con un holograma vendiéndote seguros."),
                     ("chat", "preguntan al chat qué opina", 1, (15, 30), "¿Tú qué lectura le das? Escríbelo en el chat.")],
}
# Invitados-personaje de PARODIA hecha por IA (inspirados en el estilo público de divulgadores; NO son las personas reales: sin citas textuales, sin opiniones inventadas).
INVITADOS = [
    dict(n="Dr. Michio K.", real="Michio Kaku", peso=dict(def_=3, fisica=4), sello="físico teórico divulgador: entusiasmo contagioso y voz suave, todo es «fantástico»; imagina el futuro (teletransporte, civilizaciones que dominan la energía de una estrella, viajes interestelares) y lo cuenta con asombro de niño"),
    dict(n="Dr. Neil D. T.", real="Neil deGrasse Tyson", peso=dict(def_=3, fisica=4), sello="astrofísico divulgador: «perspectiva cósmica», corrige con cariño («en realidad…»), recuerda que somos polvo de estrellas, adora señalar los errores científicos de las películas y los memes"),
    dict(n="Giorgio T.", real="Giorgio Tsoukalos", peso=dict(def_=1, alien=6), sello="el de los alienígenas ancestrales: explica TODO con visitantes de otros mundos, con tono misterioso y dramático, y remata con «no digo que fueron extraterrestres, pero…»; su pelo es legendario y Joy le sigue la corriente mientras la ciencia de consenso lo desmiente con humor"),
    dict(n="Dra. Estática", real=None, peso=dict(def_=2), sello="científica loca FICTICIA: bata chamuscada, inventos que casi explotan, habla muy rápido y se distrae con cualquier cosa brillante"),
]
REGLAS_INV = ("PERSONAJE INVITADO (parodia hecha por IA, inspirada en el estilo público de {real}; NO es la persona real): {n}. Sello: {sello}. "
              "REGLAS: interpreta a {n} SOLO con Kuroki (ella habla como el invitado; Joy entrevista). Exagera su estilo con cariño y humor, pero NO inventes citas textuales reales, NO le atribuyas opiniones, "
              "libros, hechos ni declaraciones reales, nada de política, burlas hirientes ni polémicas; los datos científicos deben ser de consenso o de la hoja de datos. "
              "Si el personaje es de ciencia dudosa, Joy o la ciencia lo corrigen con humor. ")


def elegir_invitado(prog: dict, tema: str) -> dict:
    clave = "alien" if any(w in (prog.get("nombre", "") + tema).lower() for w in ("alien", "señal", "conspira", "ovni", "extraterr", "fermi", "drake")) else \
            "fisica" if any(w in tema.lower() for w in ("agujero", "cuánt", "relativ", "espacio", "universo", "estrella", "planeta", "física", "luna")) else "def_"
    return random.Random(tema).choices(INVITADOS, [i["peso"].get(clave, i["peso"].get("def_", 1)) for i in INVITADOS])[0]


CATS_FOTO = {"noticias": ["tech", "ciencia", "juegos"], "deportes": ["deportes"], "internacional": ["mundo"], "analisis": ["tech"], "politica": ["tech"],
             "megacorp": ["tech"], "videojuegos": ["juegos"], "ia": ["tech"], "ciencia": ["ciencia"], "showkuroki": ["tech"]}
ANGULOS = ["cotidiano", "histórico", "técnico", "cultural", "del futuro", "con humor", "ético", "curioso"]
FORMATOS_DEF = ["explicado", "mito_realidad", "linea_tiempo", "debate", "top3", "entrevista", "real_inventado"]
WPS = 2.3          # palabras por segundo de la voz edge (medido): 5 min ≈ 690 palabras


def otra(q: str) -> str:
    return "kuroki" if q == "joy" else "joy"


# ───────────────────────────── nivel JORNADA: la cartelera del día ─────────────────────────────
def japon_disponible() -> bool:
    noche = os.path.join(HERE, "noche")
    return any(os.path.exists(os.path.join(noche, d, "japon.json")) for d in (os.listdir(noche) if os.path.isdir(noche) else []))


ANCLAS_F = os.path.join(HERE, "anclas.json")    # editable: programas fijos de cada jornada
ANCLAS_DEF = [{"id": "japon", "programa": "japon", "ini": "23:15", "dura": 60, "nombre": "HORA DE JAPÓN · 日本アワー", "sub": "Videojuegos en Japón · en japonés, con traducción",
               "color": "#ff8fc7", "tag": "JAPÓN", "escena": "JAPON", "si": "japon"},
              {"id": "fastpenguin", "ini": "06:00", "dura": 120, "nombre": "FAST PENGUIN", "sub": "En vivo · Blackrose juega", "color": "#ffffff", "tag": "EN VIVO", "especial": True}]


def anclas() -> list[dict]:
    a = cargar(ANCLAS_F, None)
    if a is None:
        json.dump(ANCLAS_DEF, open(ANCLAS_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        a = ANCLAS_DEF
    return [x for x in a if x.get("si") != "japon" or japon_disponible()]


def _dura_bloque() -> int:
    """Minutos de cada bloque normal (consola.json «dura_bloque»; 40 por defecto)."""
    try:
        return max(10, int(cargar(os.path.join(os.path.dirname(__file__), "consola.json"), {}).get("dura_bloque", 40)))
    except Exception:
        return 40


def jornada(fecha: str | None = None, conservar_hasta: str | None = None, desde: "dt.datetime | None" = None) -> dict:
    """Cartelera de 12:00 a 12:00 (la «fecha» es la de fecha_noche()). Slots de 45 min (40 + 5 de pausa).
    Anclas: 23:15 HORA DE JAPÓN (60 min, si hay guion) · 05:45 noticias de la madrugada. El resto lo decide el árbol de franjas."""
    fecha = fecha or fecha_noche()
    rnd = random.Random("jornada-" + fecha)
    base = dt.datetime.strptime(fecha, "%Y-%m-%d").replace(hour=12)
    bloques, cuenta, prev = [], {}, None
    t = desde or base
    fin = base + dt.timedelta(hours=24)
    fijas = sorted(((base + dt.timedelta(minutes=_min_jornada(x["ini"])), x) for x in anclas()), key=lambda y: y[0])
    while t + dt.timedelta(minutes=15) <= fin:
        hhmm = t.strftime("%H:%M")
        a = next(((ta, x) for ta, x in fijas if ta >= t - dt.timedelta(minutes=1)), None)
        if a and a[0] <= t + dt.timedelta(minutes=1):          # empieza un ancla
            bloques.append({**{k: v for k, v in a[1].items() if k != "si"}, "ini": a[0].strftime("%H:%M")})
            t = a[0] + dt.timedelta(minutes=a[1].get("dura", 40) + (0 if a[1].get("especial") else 5))
            prev = a[1].get("programa", a[1]["id"])
            continue
        dura = _dura_bloque()
        if a and a[0] < t + dt.timedelta(minutes=dura + 5):            # el ancla llega antes de completar un bloque normal
            hueco = (a[0] - t).total_seconds() / 60 - 5
            if hueco < 15:
                t = a[0]
                continue
            dura = int(hueco)
        dura = min(dura, int((fin - t).total_seconds() / 60) - 5)
        if dura < 10:
            break
        fr = FRANJA_DE(t.hour)
        if t.hour == 5 and t.minute >= 30 or t.hour == 6 and t.minute < 15:
            pid = "noticias"
        else:
            cands = [(k, v["franjas"].get(fr, 0)) for k, v in P.items() if k != prev and cuenta.get(k, 0) < v.get("max_dia", 3) and v["franjas"].get(fr, 0) > 0]
            tot = sum(w for _, w in cands)
            x, pid = rnd.random() * tot, cands[-1][0]
            for k, w in cands:
                x -= w
                if x <= 0:
                    pid = k
                    break
        v = P[pid]
        cuenta[pid] = cuenta.get(pid, 0) + 1
        bloques.append({"id": f"{pid}_{t:%H%M}", "programa": pid, "ini": hhmm, "dura": dura, "nombre": v["nombre"], "sub": v["sub"], "color": v["color"], "tag": v["tag"], "fractal": True})
        prev = pid
        t += dt.timedelta(minutes=dura + 5)
    c = {"titulo": "CARTELERA DE LA JORNADA", "jornada": fecha, "noche": f"{base:%d} → {base + dt.timedelta(days=1):%d} {base:%b}".upper(), "duracion_bloque": _dura_bloque(), "bloques": bloques}
    if conservar_hasta:      # mantiene los bloques ya anunciados de la cartelera anterior hasta esa hora (p. ej. la noche en curso)
        vieja = cargar(CARTELERA, {"bloques": []})["bloques"]
        lim = _min_jornada(conservar_hasta)
        keep = [b for b in vieja if _min_jornada(b["ini"]) < lim]
        c["bloques"] = keep + [b for b in bloques if _min_jornada(b["ini"]) >= lim]
    return c


def _min_jornada(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return ((h - 12) % 24) * 60 + m


def asegurar_jornada(forzar: bool = False) -> dict:
    """La cartelera vigente es la de esta jornada; si no, se genera (determinista: productor y director llegan a la misma)."""
    c = cargar(CARTELERA, {})
    if not forzar and c.get("jornada") == fecha_noche():
        return c
    nueva = jornada()
    tmp = CARTELERA + f".tmp{os.getpid()}"
    json.dump(nueva, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, CARTELERA)
    log.info("🗓 cartelera nueva de la jornada %s: %d programas", nueva["jornada"], len(nueva["bloques"]))
    return nueva


def parecida(a: str, b: str) -> bool:
    """¿Repite casi lo mismo? (el 4B a veces copia la línea anterior)"""
    A, B = set(re.findall(r"\w{4,}", a.lower())), set(re.findall(r"\w{4,}", b.lower()))
    return bool(A) and len(A & B) / len(A) > 0.6


def parse_json(txt: str):
    """JSON tolerante: quita ```json, toma del primer { al último }, nombres de hablante en minúscula."""
    t = re.sub(r"```(?:json)?", "", txt or "")
    m = re.search(r"[\[{].*[\]}]", t, re.S)
    if not m:
        raise ValueError("sin JSON")
    try:
        d = json.loads(m.group(0))
    except ValueError:
        d = json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)))     # coma colgando
    ls = d.get("lineas") if isinstance(d, dict) else d if isinstance(d, list) else None
    for l in ls or []:
        if isinstance(l, dict) and isinstance(l.get("quien"), str):
            l["quien"] = l["quien"].strip().lower()
    return d


async def llm_json(usuario: str, max_tokens: int, temp: float, profundo: bool = False) -> dict | list | None:
    """Pedido al cerebro (:8087, 4B → 9B) con JSON forzado por gramática: sin JSON roto."""
    import aiohttp
    from .productor import LLM_URL
    body = {"messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}], "temperature": temp, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"}, "model": "profundo" if profundo else "rapido"}
    for intento in range(2):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1800 if profundo else 300)) as s, s.post(LLM_URL, json=body) as r:
                d = await r.json(content_type=None)
            return parse_json(d["choices"][0]["message"]["content"])
        except Exception as e:  # noqa: BLE001
            log.warning("LLM %d: %s", intento + 1, str(e)[:120])
            await asyncio.sleep(2 + intento * 3)
    return None


# ───────────────────────────── nivel TRAMO: un pedido corto al 4B ─────────────────────────────
async def tramo(prog: dict, ep: str, tema: str, formato: str, angulo: str, paso: tuple, dicho: list[dict], quien: str, extra: str = "") -> list[dict]:
    pid, instr, n, (a, z), plantilla = paso
    n = max(1, min(n, 2)) if pid != "rapida" else 3     # frecuencia a un tercio (20-nov): pocas líneas, con más sustancia
    if pid == "joy":
        quien = "joy"
    elif pid == "kuroki":
        quien = "kuroki"
    previo = " / ".join(f"{l['quien']}: {l['texto'][:150]}" for l in dicho[-3:]) or "(empiezan el tema)"
    gastados = [m for m, rx in MOTIVOS if len(re.findall(rx, " ".join(l["texto"] for l in dicho), re.I)) >= 1]
    ya = " | ".join(l["texto"][:70] for l in dicho[:-3])
    dire = str(cargar(COORD, {}).get("directriz") or "").strip()
    if dire:
        extra = extra + f"Directriz de tono de la hora (de la mente interna): {dire}\n"
    dire_a = str(cargar(CONSOLA, {}).get("directriz") or "").strip()
    if dire_a:
        extra = extra + f"INDICACIÓN DE LA DIRECTORA DEL CANAL (prioridad, respétala): {dire_a}\n"
    u = (f"Programa: {prog['estilo']}.\nEpisodio: {ep}.\nTema de ahora (5 minutos): {tema} — formato «{formato}», ángulo {angulo}.\n{extra}"
         f"Lo último que dijeron: {previo}\n" + (f"Antes ya dijeron (NO lo repitas ni lo reformules): {ya}\n" if ya else "") +
         (f"MOTIVOS YA GASTADOS en este tema (PROHIBIDO volver a usarlos): {', '.join(gastados)}. Busca chistes nuevos y concretos del tema.\n" if gastados else "") +
         "No empieces ninguna línea con «Exacto», «Claro» ni «Bienvenidos».\n" +
         f"PASO «{pid}»: {instr}. Escribe {n} intervenciones alternadas empezando por {quien} (sigue {otra(quien)}), de {a} a {z} palabras cada una. "
         "Que se note que se escuchan: responden a lo anterior y AVANZAN (una idea, dato o chiste NUEVO por línea; prohibido volver a contar el titular). "
         "Humor con variedad: las megacorporaciones ficticias, la lluvia neón, 2049 y la tarjeta de 6 GB son condimento: como mucho una mención por paso, no en cada línea.\n"
         'Devuelve SOLO JSON: {"lineas":[{"quien":"joy","texto":"…"}]}')
    d = await llm_json(u, 200 + n * z * 3, 0.65)
    ls = lineas_ok((d or {}).get("lineas") if isinstance(d, dict) else d if isinstance(d, list) else None, 1)
    out = []
    for l in ls[: n + 1]:
        t = re.sub(r"^\s*(joy|kuroki)\s*[:：,-]\s*", "", l["texto"], flags=re.I).strip()
        if len(t) > 6 and not any(parecida(t, x["texto"]) for x in dicho + out):
            out.append({"quien": l["quien"], "texto": t})
    if out:
        return out
    log.info("      tramo «%s» sin LLM: plantilla", pid)
    return [{"quien": quien, "texto": plantilla.format(tema=tema)}]


async def tema_completo(prog: dict, ep: str, tema: str, formato: str, angulo: str, abre: str, extra: str = "") -> dict:
    dicho: list[dict] = []
    q = abre
    inv = elegir_invitado(prog, tema) if formato == "entrevista" else None
    if inv:
        extra = extra + REGLAS_INV.format(**{k: (v or "una persona real") if k == "real" else v for k, v in inv.items()}) + "\n"
        q = "joy"
    for paso in FORMATOS[formato]:
        if inv:
            paso = (paso[0], paso[1].replace("{inv}", inv["n"]), *paso[2:])
            q = "joy"
        ls = await tramo(prog, ep, tema, formato, angulo, paso, dicho, q, extra)
        dicho += ls
        q = otra(ls[-1]["quien"]) if ls else otra(q)
    pal = sum(len(l["texto"].split()) for l in dicho)
    diag = await diagrama(prog, tema, formato, dicho) if formato in DIAGRAMABLES else None
    intl = await internacional(tema, dicho)
    return {"tipo": "charla", "tema": limpia(tema)[:70], "diagrama": diag, "intl": intl, "sub": (f"entrevista con {inv['n']} (parodia IA)" if inv else f"{formato.replace('_', ' ')} · {angulo}")[:80], "lineas": dicho, "seg": round(pal / WPS + len(dicho) * 1.2)}


async def internacional(tema: str, dicho: list[dict]) -> dict | None:
    """Cierre para la audiencia internacional (pedido 20-nov: «el japonés tiene que escucharse, y también en inglés a veces»): una frase en japonés
    y una en inglés que resumen el tema con humor e invitan al chat; el director dice una (con traducción en pantalla)."""
    resumen = " / ".join(l["texto"][:110] for l in dicho[-6:])
    u = (f"Tema de TV: «{tema}». Lo que se dijo: {resumen}\n"
         "Escribe el cierre para la audiencia internacional del canal: UNA frase en japonés natural (máx. 45 caracteres) y UNA en inglés (máx. 22 palabras), "
         "que resuman el tema con un toque de humor y saluden o inviten al chat; y la traducción al español de cada una. Sin emojis. "
         'Devuelve SOLO JSON: {"ja":"…","ja_es":"…","en":"…","en_es":"…"}')
    d = await llm_json(u, 300, 0.6)
    if not isinstance(d, dict) or not re.search(r"[぀-ヿ一-鿿]", str(d.get("ja", ""))) or len(str(d.get("en", ""))) < 8:
        return None
    return {k: limpia(str(d.get(k, "")))[:200] for k in ("ja", "ja_es", "en", "en_es")}


MOTIVOS = [("lluvia neón / lluvia", r"lluvia"), ("Neón Holdings", r"ne[oó]n holdings"), ("Doll Dynamics", r"doll dynamics"), ("Megacorp Rosa", r"megacorp"),
           ("la tarjeta de 6 GB", r"6 ?g|seis gigas"), ("hologramas", r"holograma"), ("2049", r"2049|dos mil cuarenta"), ("melancolía", r"melancol"), ("¿Quieres saber más?", r"quieres saber m")]
DIAGRAMABLES = {"explicado", "linea_tiempo", "pronostico", "analisis2049", "mito_realidad", "top3", "parlamento"}


async def diagrama(prog: dict, tema: str, formato: str, dicho: list[dict]) -> dict | None:
    """Un DIAGRAMA simple para explicar el tema en pantalla (pedido 20-nov): 3 a 5 cajas con flechas. Una llamada corta; si falla, sin diagrama."""
    resumen = " / ".join(l["texto"][:120] for l in dicho[:8])
    u = (f"Tema de TV: «{tema}» (formato {formato}). Lo que se dijo: {resumen}\n"
         "Haz un DIAGRAMA para la pantalla que explique el tema de un vistazo: tipo «flujo» (pasos con flechas), «linea» (línea de tiempo) o «comparar» (dos columnas). "
         "De 3 a 5 cajas; cada caja con un título de máximo 4 palabras y una nota de máximo 9 palabras; solo hechos seguros (o lo dicho como ficción, marcado «2049»). "
         'Devuelve SOLO JSON: {"tipo":"flujo|linea|comparar","titulo":"…","cajas":[{"t":"…","n":"…"}]}')
    d = await llm_json(u, 350, 0.4)
    if not isinstance(d, dict) or not isinstance(d.get("cajas"), list):
        return None
    cajas = [{"t": limpia(str(c.get("t", "")))[:34], "n": limpia(str(c.get("n", "")))[:80]} for c in d["cajas"] if isinstance(c, dict) and c.get("t")][:5]
    if len(cajas) < 3:
        return None
    return {"tipo": d.get("tipo") if d.get("tipo") in ("flujo", "linea", "comparar") else "flujo", "titulo": limpia(str(d.get("titulo") or tema))[:60], "cajas": cajas}


# ───────────────────────────── PERIODISTA por lote: N titulares → 1 llamada ─────────────────────────────
LOTE_SIS = ("Eres el equipo de prensa de BlackRose TV: la PERIODISTA eligió estos titulares reales; tú escribes el guion del noticiero completo. "
            "Conducen dos nekos cibernéticas: {cond} (conductora de noticias, presenta cada nota y da paso) y {rep} (reportera: hace el «enlace», explica el "
            "contexto general, por qué importa y qué no se sabe aún). Estilo del programa: {estilo}. "
            "REGLAS: solo puedes afirmar lo que dice cada titular y su fuente; el contexto es general y marcado como contexto; nada de cifras, "
            "nombres ni resultados que no estén en el titular; lo futuro o condicional NO es un hecho. Español latino, frases para decir en voz alta. "
            "Por cada titular: 2 o 3 líneas (25 a 45 palabras cada una): {cond} lo presenta con su fuente → {rep} hace el enlace usando el RESUMEN si viene → {remate}"
            "la última línea de la ÚLTIMA nota invita al chat a opinar. "
            'Devuelve SOLO JSON: {{"notas":[{{"lineas":[{{"quien":"joy|kuroki","texto":"…"}}]}}]}} con una nota por titular, en el mismo orden.')
LLAMADAS = {"lote": 0, "tramo": 0}


async def noticiero_lote(prog: dict, tits: list[dict], abre: str) -> list[dict]:
    """Nervio + cerebro: el RSS ya trajo los titulares (sin LLM); UNA llamada escribe todas las notas del grupo.
    Si el LLM falla, cada nota se lee tal cual con plantilla (cero LLM): la emisión nunca queda muda."""
    cond, rep = abre, otra(abre)
    lista = "\n".join(f"{i + 1}. «{x['titulo']}» — fuente: {x['fuente']}, hace {x['horas']} h" + (f"\n   RESUMEN de la fuente: {x['resumen'][:380]}" if x.get("resumen") else "")
                      for i, x in enumerate(tits))
    dire_a = str(cargar(CONSOLA, {}).get("directriz") or "").strip()
    if dire_a:
        lista += f"\n\nINDICACIÓN DE LA DIRECTORA DEL CANAL (prioridad): {dire_a}"
    LLAMADAS["lote"] += 1
    remate = ("la última línea de cada nota es un REMATE con humor seco (o una mini proyección satírica a 2049 dicha como chiste), salvo si la noticia es una tragedia: ahí, respeto. "
              if prog.get("remate", True) and prog.get("tag") not in ("MUNDO", "ANÁLISIS") else "")
    d = await llm_json(LOTE_SIS.format(cond=cond.capitalize(), rep=rep.capitalize(), estilo=prog["estilo"], remate=remate) + "\n\nTITULARES:\n" + lista,
                       380 * len(tits) + 200, 0.75)
    notas = (d or {}).get("notas") if isinstance(d, dict) else d if isinstance(d, list) else None
    out = []
    for i, x in enumerate(tits):
        ls = []
        try:
            for l in (notas[i].get("lineas") or []):
                q = str(l.get("quien", "")).lower()
                t = limpia(str(l.get("texto", "")))
                if q in ("joy", "kuroki") and len(t) > 6:
                    ls.append({"quien": q, "texto": t})
        except (TypeError, IndexError, AttributeError):
            ls = []
        if len(ls) < 2:      # plantilla: se lee el titular real, sin inventar
            ls = [{"quien": cond, "texto": f"{random.choice(['Atención a esta:', 'Sigue:', 'También:', 'Otra más:'])} {x['titulo']}. Lo informa {x['fuente']}."},
                  {"quien": rep, "texto": "Por ahora es lo que dice el titular; habrá que ver cómo sigue. ¿Tú qué opinas? Escríbelo en el chat."}]
        pal = sum(len(l["texto"].split()) for l in ls)
        img = x.get("img")
        if not img:                 # titular de Google News: se busca la misma nota en los feeds con foto
            try:
                from .fotos import para
                img = await asyncio.to_thread(lambda: para(x["titulo"], "*")[1])
            except Exception:  # noqa: BLE001
                img = None
        out.append({"tipo": "charla", "tema": limpia(x["titulo"])[:70], "sub": f"{x['fuente']} · hace {x['horas']} h"[:80], "lineas": ls[:3],
                    "seg": round(pal / WPS + len(ls) * 1.2), "lote": bool(notas), "imgs": [img] if img else []})
    log.info("   📰 periodista: %d titulares en 1 llamada (%s)", len(tits), "ok" if notas else "plantilla")
    return out


# ───────────────────────────── nivel EPISODIO: semilla → 3 facetas ─────────────────────────────
async def facetas(prog: dict, semilla: str, rnd: random.Random, hoja: str = "") -> list[str]:
    u = (f"Programa: {prog['estilo']}.\n{hoja}El episodio de hoy parte de: «{semilla}». Propón 4 temas de 5 minutos DISTINTOS entre sí que salgan de ahí "
         "(una faceta cada uno, títulos concretos de hasta 9 palabras, solo hechos seguros).\n" 'Devuelve SOLO JSON: {"titulo_episodio":"…","temas":["…","…","…","…"]}')
    d = await llm_json(u, 300, 0.9)
    ts = [limpia(t)[:90] for t in ((d or {}).get("temas") or [] if isinstance(d, dict) else []) if isinstance(t, str) and 6 < len(t) < 120]
    if len(ts) >= 3:
        return [limpia(str(d.get("titulo_episodio") or semilla))[:70]] + ts[:4]
    ang = rnd.sample(ANGULOS, 4)
    return [semilla] + [f"{semilla}, visto desde lo {a}" if a != "con humor" else f"{semilla}, con humor" for a in ang]


def semillas_de(pid: str, usados: dict, rnd: random.Random) -> list[str]:
    v = P[pid]
    extra = [s for s in cargar(EXTRA, {}).get(pid, []) if isinstance(s, str)]
    coord = [t for t in (cargar(COORD, {}).get("temas", {}).get(pid) or []) if isinstance(t, str) and 6 < len(t) < 140]
    pool = list(v.get("semillas", []))
    rnd.shuffle(pool)
    pool.sort(key=lambda s: (usados.get("tema:" + s, 0), 0 if hay_hoja(s) else 1))     # a igual uso, las que el 9B ya investigó
    from .tendencias import de_programa
    alice = [t for t in (cargar(CONSOLA, {}).get("temas", {}).get(pid) or []) if isinstance(t, str) and len(t) > 3]
    tend = [f"Tendencia de hoy: {t['termino']}" + (f" ({t['contexto']})" if t.get("contexto") else "") for t in de_programa(pid, 1)]
    mias = [s for s in alice if usados.get("tema:" + s, 0) == 0]                 # lo que pidió Alice en la consola: SIEMPRE primero
    nuevas = [s for s in tend + coord + extra if usados.get("tema:" + s, 0) == 0 and s not in mias]
    nuevas.sort(key=lambda s: 0 if hay_hoja(s) else 1)      # lo investigado por el 9B va primero si es nuevo
    return mias + nuevas + [s for s in pool if s not in nuevas and s not in mias]


HOJAS = os.path.join(HERE, "hojas")      # hojas de datos por semilla: las prepara el 9B por adelantado (pensador.py)


def ruta_hoja(semilla: str) -> str:
    import hashlib
    os.makedirs(HOJAS, exist_ok=True)
    return os.path.join(HOJAS, hashlib.sha1(semilla.strip().lower().encode()).hexdigest()[:16] + ".json")


def hay_hoja(semilla: str) -> bool:
    return os.path.exists(ruta_hoja(semilla))


async def investigar(prog: dict, semilla: str, profundo: bool = True) -> dict | None:
    """Hoja de hechos seguros sobre una semilla. profundo=True → 9B (ThinkPad, lento, se hace por adelantado)."""
    u = (f"Vas a preparar la HOJA DE DATOS de un episodio de televisión de divulgación ({prog['estilo']}) sobre: «{semilla}».\n"
         "Escribe de 8 a 12 hechos SEGUROS y verificables (los que saldrían en cualquier enciclopedia), una frase cada uno; si no estás segura de una fecha, cifra o nombre, NO la pongas. "
         "Nada de vida privada, rumores ni chismes. Agrega 2 «leyendas o errores comunes» marcados como tales.\n"
         'Devuelve SOLO JSON: {"hechos":["…"],"leyendas":["…"]}')
    d = await llm_json(u, 800 if profundo else 600, 0.3 if profundo else 0.2, profundo=profundo)
    if not isinstance(d, dict) or not d.get("hechos"):
        return None
    h = {"semilla": semilla, "hechos": [limpia(x)[:220] for x in d.get("hechos", []) if isinstance(x, str)][:12],
         "leyendas": [limpia(x)[:200] for x in d.get("leyendas", []) if isinstance(x, str)][:3], "por": "9b" if profundo else "4b", "t": time.strftime("%Y-%m-%d %H:%M")}
    if profundo:      # solo las del 9B quedan guardadas para reusar
        json.dump(h, open(ruta_hoja(semilla), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return h


async def hoja_datos(prog: dict, semilla: str) -> str:
    """Hoja del 9B si ya la investigó; si no, una rápida del 4B (temperatura baja). Texto listo para el prompt del 4B."""
    h = cargar(ruta_hoja(semilla), None) or await investigar(prog, semilla, profundo=False)
    if not h:
        return "No hay hoja de datos: NO afirmes fechas, cifras, nombres propios ni datos biográficos; habla de ideas generales, opina y pregunta.\n"
    log.info("   hoja de datos de «%s» (%s, %d hechos)", semilla[:40], h.get("por"), len(h["hechos"]))
    return ("HOJA DE DATOS (lo ÚNICO que puedes afirmar como hecho; no inventes fechas, cifras, nombres ni vida privada fuera de esto):\n- " + "\n- ".join(h["hechos"])
            + ("\nLEYENDAS / ERRORES COMUNES (solo como tales):\n- " + "\n- ".join(h["leyendas"]) if h.get("leyendas") else "") + "\n")


# ───────────────────────────── el PROGRAMA completo → paquete ─────────────────────────────
async def producir(b: dict, forzar: bool = False) -> str:
    ruta = ruta_paquete(b["id"])
    if os.path.exists(ruta) and not forzar:
        return ruta
    pid = b["programa"]
    prog = P[pid]
    t0 = time.time()
    rnd = random.Random(f"{fecha_noche()}-{b['id']}")
    usados = cargar(USADOS, {})
    log.info("▶ produciendo %s (%s)", b["id"], prog["nombre"])
    episodios: list[tuple[str, list[tuple[str, str]]]] = []     # (título, [(tema, extra)])
    formatos = prog.get("formatos") or FORMATOS_DEF
    if prog.get("rss"):
        from .tendencias import de_programa
        from .fotos import titulares_foto
        consultas = [t["termino"] for t in de_programa(pid, 2)] + rnd.sample(prog["rss"], min(4, len(prog["rss"])))   # tendencias del día primero
        quiero = 8 if prog.get("formatos") == ["noticia"] else 3
        cats = CATS_FOTO.get(pid)
        tits = []
        if cats:      # primero notas de feeds directos CON FOTO (y resumen real); completa Google News
            try:
                tits = await asyncio.to_thread(titulares_foto, cats, set(usados.get("_titulares", [])), quiero, prog["rss"] + list(prog.get("semillas", []))[:4])
            except Exception as e:  # noqa: BLE001
                log.warning("titulares con foto: %s", e)
        if len(tits) < quiero:
            tits += await titulares(consultas[:5], set(usados.get("_titulares", [])) | {re.sub(r"\W+", "", x["titulo"].lower())[:60] for x in tits}, quiero - len(tits))
        if pid not in ("internacional", "analisismil"):      # la sátira y el humor no tocan elecciones, migración ni tragedias
            from .fotos import VETO
            tits = [x for x in tits if not VETO.search(x["titulo"] + " " + x.get("resumen", "")[:200])]
        log.info("   %d titulares reales (%d con foto propia)", len(tits), sum(1 for x in tits if x.get("img")))
    else:
        tits = []
    noticia_solo = formatos == ["noticia"]
    if noticia_solo:
        if not tits:      # sin RSS: el noticiero se vuelve divulgación del mismo rubro (árbol: sin datos → plan B)
            formatos = ["explicado", "debate"]
            tits = []
        for i in range(0, min(8, len(tits)), 4):
            episodios.append((f"Titulares {i // 4 + 1}", [("__lote__", tits[i:i + 4])]))
    if not episodios:
        sems = semillas_de(pid, usados, rnd)
        n_ep = 1 if prog.get("radio") else 2          # menos charla, más aire (20-nov): 2 episodios de 3 temas
        if tits and not noticia_solo and "analisis2049" not in formatos:      # programas con un pie en la actualidad: el 1.er episodio parte de titulares reales
            episodios.append(("Actualidad", [("__lote__", tits[:3])]))
            n_ep = 1
        elif tits and "analisis2049" in formatos:    # análisis / parlamento: cada titular real es un tema del formato propio
            episodios.append(("La señal de hoy", [(x["titulo"], f"Titular real ({x['fuente']}): {x['titulo']}. " + (f"Resumen de la fuente: {x.get('resumen', '')[:380]}\n" if x.get("resumen") else "\n"), x.get("img")) for x in tits[:3]]))
            n_ep = 1
        for s in (sems or ["la tecnología que nos rodea"])[:n_ep]:
            hoja = await hoja_datos(prog, s)
            f = await facetas(prog, s, rnd, hoja)
            try:
                from .fotos import wiki
                fotos_s = await asyncio.to_thread(wiki, re.sub(r"^Tendencia de hoy:\s*", "", s), 4)
            except Exception:  # noqa: BLE001
                fotos_s = []
            n_t = 2
            temas_ep = f[1:1 + n_t]
            if not fotos_s:      # semilla abstracta sin artículo: se busca por cada tema
                for t in temas_ep:
                    try:
                        fotos_s += await asyncio.to_thread(wiki, t, 1)
                    except Exception:  # noqa: BLE001
                        pass
            episodios.append((f[0], [(t, hoja, fotos_s[k % len(fotos_s)] if fotos_s else None) for k, t in enumerate(temas_ep)]))
            usados["tema:" + s] = usados.get("tema:" + s, 0) + 1
    # medios: música de las playlists sin copyright (RADIO 2049) + a lo sumo 1 video con licencia corto (los MIDI quedaron fuera, 20-nov)
    from .radio import para_programa
    sel_v, _ = elegir_medios(pid, usados)
    sel_v = [v for v in sel_v if v["dur"] <= 540][:0 if prog.get("radio") else 1]
    sel_m = para_programa(pid, 9 if prog.get("radio") else 2, usados, rnd)
    medios = [{"tipo": "video", "id": m["id"], "archivo": m["archivo"], "titulo": m["titulo"], "atribucion": m["atribucion"], "dur": round(m["dur"]), "intro": [], "outro": []} for m in sel_v] + \
             [dict(m) for m in sel_m]
    cortes = [{"tipo": "corte", "texto": t, "sub": s, "dice": rnd.choice(["joy", "kuroki"])} for t, s in rnd.sample(CORTES_FIJOS, min(2, len(CORTES_FIJOS)))]
    items: list[dict] = []
    abre = prog["abre"]
    for e, (titulo, temas) in enumerate(episodios[:3]):
        temas = [t if len(t) == 3 or t[0] == "__lote__" else (*t, None) for t in temas]
        items.append({"tipo": "corte", "texto": f"Episodio {e + 1}: {titulo}", "sub": prog["nombre"], "dice": abre})
        if temas and temas[0][0] == "__lote__":     # noticiero: una llamada para todo el grupo
            notas = await noticiero_lote(prog, temas[0][1], abre)
            for k, it in enumerate(notas):
                items.append(it)
                if k == 1 and cortes:
                    items.append(cortes.pop(0))
            if medios:
                items.append(medios.pop(0))
            continue
        for k, (tema, extra, foto) in enumerate(temas):
            fmt = ("analisis2049" if "analisis2049" in formatos and extra.startswith("Titular") else "noticia") if extra.startswith("Titular") else \
                  formatos[(e * 3 + k + rnd.randrange(len(formatos))) % len(formatos)]
            ang = rnd.choice(ANGULOS) if fmt != "noticia" else "informativo"
            log.info("   ep%d tema%d: %s [%s · %s]", e + 1, k + 1, tema[:60], fmt, ang)
            it = await tema_completo(prog, titulo, tema, fmt, ang, abre if k % 2 == 0 else otra(abre), extra)
            it["imgs"] = [foto] if foto else []
            items.append(it)
            if prog.get("radio") and medios:          # radio: tema hablado corto → 3 o 4 canciones
                for _ in range(4):
                    if medios:
                        items.append(medios.pop(0))
            if k == 1 and cortes:
                items.append(cortes.pop(0))
        if medios:
            items.append(medios.pop(0))
    items += medios + cortes
    usados["_titulares"] = (usados.get("_titulares", []) + [re.sub(r"\W+", "", x["titulo"].lower())[:60] for x in tits])[-300:]
    for m in sel_v + sel_m:
        usados[m["id"]] = usados.get(m["id"], 0) + 1
    log.info("   llamadas LLM del bloque: %s lote(s) de noticias", LLAMADAS["lote"])
    pq = {"bloque": b["id"], "programa": pid, "fecha": fecha_noche(), "creado": time.strftime("%H:%M:%S"), "fractal": True, "items": items,
          "estado": {"episodios": len(episodios[:3]), "temas": sum(1 for i in items if i["tipo"] == "charla"),
                     "seg_charla": sum(i.get("seg", 0) for i in items if i["tipo"] == "charla"), "medios": sum(1 for i in items if i["tipo"] in ("video", "musica"))}}
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(pq, f, ensure_ascii=False, indent=1)
    os.replace(ruta + ".tmp", ruta)
    json.dump(usados, open(USADOS, "w", encoding="utf-8"), ensure_ascii=False)
    log.info("✔ %s listo en %.0f s: %s", b["id"], time.time() - t0, pq["estado"])
    return ruta


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    a = sys.argv[1:] or ["jornada"]
    if a[0] == "jornada":
        c = asegurar_jornada("--forzar" in a)
        for b in c["bloques"]:
            print(b["ini"], b["id"], b["nombre"])
    elif a[0] == "producir":
        c = asegurar_jornada()
        b = next(x for x in c["bloques"] if x["id"] == a[1])
        print(asyncio.run(producir(b, "-f" in a)))
    elif a[0] == "tema":
        r = asyncio.run(tema_completo(P["tecnologia"], "Prueba", a[1], a[2] if len(a) > 2 else "explicado", "cotidiano", "joy"))
        for l in r["lineas"]:
            print(f"{l['quien']:7} {l['texto']}")
        print("≈", r["seg"], "s")
