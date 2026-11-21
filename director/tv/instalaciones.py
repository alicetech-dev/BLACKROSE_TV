"""INSTALACIONES DE BLACKROSE TV — catálogo único de los sets del estudio Unity 2049 (~/BlackroseTV_build, API :8836).

Lo comparten el director (rotación de sets por tema), la consola (plano de las instalaciones) y el estudio de programas.
Si Unity está arriba, la consola lee la lista real de /api/estado; esto es la ficha que no cambia: dónde está, para qué sirve,
qué programas le calzan y qué planos tiene.
"""
from __future__ import annotations

# x = posición en el eje del estudio (metros en Unity; la cámara mira hacia −Z desde +Z).
SETS: dict[str, dict] = {
    "estelar":     dict(corto="Noche Estelar", x=-82, titulo="Noche Estelar", color="#ff2fd6", icono="🎤", que="Escenario de concierto con pantalla synthwave, banda y grada.",
                        planos=["amplio", "escenario", "banda", "grada", "joy", "kuroki"], uso=["musica", "showkuroki", "teatro", "vtubing"]),
    "prensa":      dict(corto="Prensa", x=-52, titulo="Conferencia de Prensa", color="#ffd166", icono="🎙", que="Mesa de DT con muro de marcas ficticias; Joy y Kuroki como D.T.",
                        planos=["amplio", "prensa", "dos", "joy", "kuroki"], uso=["megacorp", "politica", "fastpenguin"]),
    "deportes":    dict(corto="Deportes", x=-26, titulo="BRTV Deportes", color="#7dffc4", icono="⚽", que="Cancha de fondo, mesa de conducción, vitrina de trofeos.",
                        planos=["amplio", "dos", "lateral", "trofeos", "joy", "kuroki"], uso=["deportes", "videojuegos"]),
    "noticiario":  dict(corto="Noticiario", x=0, titulo="Noticiario + Redacción", color="#00e5ff", icono="📰", que="Mesa central, ventanal a la ciudad 2049, redacción con periodistas y el NÚCLEO de datos tras el vidrio.",
                        planos=["amplio", "dos", "grua", "lateral", "lateral_b", "redaccion", "nucleo", "joy", "kuroki"], uso=["noticias", "internacional", "analisis", "tecnologia", "ia"]),
    "tiempo":      dict(corto="El Tiempo", x=26, titulo="El Tiempo 2049", color="#4fd8ff", icono="🌐", que="Planeta holográfico, mapa climático y pantallas de ciudades.",
                        planos=["amplio", "mapa", "planeta", "joy", "kuroki"], uso=["ciencia", "megaconst", "alien", "conspira"]),
    "panel":       dict(corto="El Panel", x=50, titulo="El Panel", color="#ff6fb5", icono="🛋", que="Círculo de sillones rosas bajo arcos de neón: la conversación.",
                        planos=["amplio", "dos", "picado", "joy", "kuroki"], uso=["sobremesa", "linux", "historia", "devgames", "tecnooculta", "hackers"]),
    "entrevistas": dict(corto="Entrevistas", x=76, titulo="Entrevistas · Poder 2049", color="#b98cff", icono="🪑", que="Dos sillones, pantalla con el logo y columnas de luz. Joy entrevista, Kuroki hace al invitado.",
                        planos=["amplio", "dos", "perfil", "joy", "kuroki"], uso=["entrevista", "historia"]),
    "militar":     dict(corto="Militar", x=76, titulo="Análisis Militar", color="#7be0a8", icono="🛰", que="Mesa táctica holográfica con radar, mapas y datos. Misma sala que Entrevistas.",
                        planos=["amplio", "dos", "mesa", "joy", "kuroki"], uso=["milttech", "analisismil", "hackers"]),
}

# Circuito de sets por programa: el director avanza al siguiente set en cada tema (charla), así un programa de 40 min no se queda en una sola pared.
# El primero es el de arranque. Lo que no figura aquí cae en «panel» ↔ «entrevistas».
RUTAS: dict[str, list[str]] = {
    "noticias": ["noticiario", "tiempo", "noticiario"], "internacional": ["noticiario", "militar", "noticiario"], "analisis": ["noticiario", "panel"],
    "deportes": ["deportes", "prensa", "deportes"], "videojuegos": ["deportes", "panel"], "musica": ["estelar"], "showkuroki": ["estelar", "panel"],
    "teatro": ["estelar", "entrevistas"], "vtubing": ["estelar", "panel"],
    "milttech": ["militar", "panel", "militar"], "analisismil": ["militar", "noticiario"], "hackers": ["militar", "panel"],
    "ciencia": ["tiempo", "panel"], "megaconst": ["tiempo", "panel"], "alien": ["tiempo", "militar", "panel"], "conspira": ["panel", "tiempo"],
    "entrevista": ["entrevistas"], "historia": ["entrevistas", "panel"], "sobremesa": ["panel", "entrevistas"],
    "politica": ["prensa", "panel"], "megacorp": ["prensa", "panel"], "fastpenguin": ["prensa"],
}
RUTA_DEF = ["panel", "entrevistas", "panel"]


def ruta(programa: str) -> list[str]:
    return RUTAS.get(programa) or RUTA_DEF


def set_inicial(bloque: dict, programa: str) -> str:
    """Set con el que arranca un bloque: el que fijó el usuario (set_base) o el primero de la ruta del programa."""
    s = (bloque or {}).get("set_base")
    return s if s in SETS else ruta(programa)[0]


# Otras instalaciones: no son sets de Unity, son escenas de OBS (2D/WebGL). Se muestran en el plano como «anexos».
ANEXOS = [
    dict(escena="SALA DE CONTROL", icono="🕹", titulo="Sala de control 3D", que="Pieza hacker y cuarto de Joy en WebGL; cortes con noticias con foto, tendencias y cámaras de seguridad."),
    dict(escena="TV NOCHE", icono="📺", titulo="Pantalla grande", que="Videos y radio: pantalla a todo el cuadro sin rostros."),
    dict(escena="JAPON", icono="🗻", titulo="Hora de Japón", que="Fuji + sakura, guion en japonés con traducción."),
    dict(escena="FAST PENGUIN", icono="🐧", titulo="Fast Penguin", que="Juego en vivo con puntajes, party y chat."),
    dict(escena="AJUSTE", icono="🎚", titulo="Carta de ajuste", que="Barras SMPTE y cuenta regresiva."),
]

# Recetas de programa para arrancar en el estudio de programas: cada tramo es (set, título del tramo, cámara, nota para el borrador de IA).
PLANTILLAS: list[dict] = [
    dict(id="noticiero_clima", nombre="Noticiero con clima y redacción", sub="Titulares, el tiempo y un enlace desde la redacción", set_base="noticiario", color="#00e5ff", tag="NOTICIERO",
         tramos=[("noticiario", "Titulares del día", "auto", "abren con 2 titulares y se reparten la nota"), ("noticiario", "Desde la redacción", "redaccion", "Kuroki hace el enlace desde la redacción"),
                 ("tiempo", "El tiempo 2049", "planeta", "pronóstico exagerado de ciudades y bases"), ("noticiario", "Cierre y despedida", "dos", "resumen y pregunta al chat")]),
    dict(id="postpartido", nombre="Post-partido: estudio y conferencia", sub="Análisis en la cancha y rueda de prensa de los D.T.", set_base="deportes", color="#7dffc4", tag="DEPORTES",
         tramos=[("deportes", "El partido en 2 minutos", "amplio", "resumen del partido"), ("deportes", "Los trofeos", "trofeos", "historia de un trofeo"),
                 ("prensa", "Rueda de prensa", "prensa", "Joy y Kuroki como D.T. responden preguntas absurdas"), ("deportes", "Cierre", "dos", "pronóstico de la próxima fecha")]),
    dict(id="noche_estelar", nombre="Noche Estelar", sub="Show de variedades con escenario, banda y charla de sofá", set_base="estelar", color="#ff2fd6", tag="SHOW",
         tramos=[("estelar", "Apertura en el escenario", "escenario", "monólogo de apertura con humor"), ("estelar", "Con la banda", "banda", "presentan el tema musical"),
                 ("panel", "Charla de sofá", "picado", "conversan de lo que pasó en la semana"), ("estelar", "Gran final", "grada", "despedida con baile")]),
    dict(id="entrevista_poder", nombre="Entrevista · Poder 2049", sub="Joy entrevista, Kuroki hace al invitado ficticio", set_base="entrevistas", color="#b98cff", tag="ENTREVISTA",
         tramos=[("entrevistas", "Presentación del invitado", "amplio", "presentan al invitado (personaje de parodia, no persona real)"), ("entrevistas", "Las preguntas incómodas", "perfil", "tres preguntas filosas con humor"),
                 ("entrevistas", "Pregunta del chat", "dos", "una pregunta del chat y la despedida")]),
    dict(id="mesa_tactica", nombre="Mesa táctica", sub="Tecnología militar vista desde la mesa holográfica", set_base="militar", color="#7be0a8", tag="DEFENSA",
         tramos=[("militar", "El tema del día", "mesa", "explican la tecnología con ejemplos civiles"), ("militar", "Mapa y datos", "amplio", "repasan el contexto con datos verificables"),
                 ("panel", "Debate de sofá", "dos", "se contradicen con cariño: ¿beneficio o riesgo?")]),
    dict(id="ciencia_circuito", nombre="Laboratorio en tres salas", sub="Ciencia que recorre el planeta, la redacción y el panel", set_base="tiempo", color="#4fd8ff", tag="CIENCIA",
         tramos=[("tiempo", "La pregunta", "planeta", "plantean la pregunta científica"), ("noticiario", "El dato duro", "nucleo", "cifras y fuentes desde el núcleo de datos"),
                 ("panel", "¿Y entonces?", "picado", "opinan y cierran con pregunta al chat")]),
]
