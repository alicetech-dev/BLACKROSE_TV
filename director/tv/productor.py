"""PRODUCTOR de BlackRose TV (noche): el agente que CREA el contenido de cada bloque de la cartelera.

Corre como servicio (tv-productor.service) y va un par de bloques por delante del Director de TV:
  · pide a Grok (grok_shim :8087, el mismo cerebro de las dolls) las charlas de Joy y Kuroki, el sketch, los «cortes» tipo MTV y las
    presentaciones de cada video; para noticieros/deportes parte de titulares REALES (Google News) y solo puede afirmar lo que dicen.
  · elige los videos y la música de la biblioteca (tv/biblioteca.json: solo material con licencia que permite emitirlo) sin repetir.
  · deja el paquete en tv/noche/<fecha>/<bloque>.json; el Director lo lee cuando llega la hora.
Si Grok falla, el paquete sale igual (con lo que se pudo) y el Director rellena con música y cortes: la emisión nunca queda muda.
  python -m director.tv.productor [bloque|todo|demonio]
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

import aiohttp

from ..show_kuroki import titulares

log = logging.getLogger("productor")
HERE = os.path.dirname(os.path.abspath(__file__))
LLM_URL = os.environ.get("BRTV_LLM_URL", "http://127.0.0.1:8087/v1/chat/completions")
CARTELERA = os.path.join(HERE, "cartelera.json")
BIBLIO = os.path.join(HERE, "biblioteca.json")
USADOS = os.path.join(HERE, "usados.json")
COORD = os.path.join(HERE, "coordinacion.json")      # lo escribe orquesta.py (UNA llamada a Grok cada 2 h): directriz + temas


def fecha_noche() -> str:
    """La «noche» empieza a las 22:30 y termina a las 06:00: antes de las 12:00 pertenece a la noche del día anterior."""
    n = dt.datetime.now()
    return (n - dt.timedelta(days=1) if n.hour < 12 else n).strftime("%Y-%m-%d")


def ruta_paquete(bid: str, fecha: str | None = None) -> str:
    d = os.path.join(HERE, "noche", fecha or fecha_noche())
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, bid + ".json")


SISTEMA = (
    "Eres el equipo de guion de BLACKROSE TV, el canal 24/7 de la CORPORACIÓN BLACKROSE, conducido por dos nekos cibernéticas, con estética cyberpunk tipo MTV. "
    "TONO DE TODO EL CANAL: comedia y sátira futurista al estilo de Paul Verhoeven (RoboCop, Starship Troopers, Total Recall: noticieros corporativos impecables que dicen cosas absurdas, "
    "anuncios de megacorporaciones ficticias que terminan en «¿Quieres saber más?») con la melancolía neón de Blade Runner 2049 (lluvia, hologramas, preguntas sobre qué es ser humano). "
    "Divertido primero: chistes secos, ironía, remates, exageración; nada de clase magistral ni tono de enciclopedia. La sátira apunta a sistemas, burocracia, propaganda y "
    "megacorporaciones FICTICIAS (Doll Dynamics, Neón Holdings, Megacorp Rosa), NUNCA a personas reales, partidos, gobiernos, religiones ni grupos. La Corporación Blackrose se ríe de sí misma. "
    "Las personas reales (empresarios, políticos, famosos) NUNCA aparecen en escenas de ficción, anuncios inventados ni proyecciones 2049, ni se les atribuyen dichos: solo se cita lo que dice la noticia. "
    "Hay dos conductoras, nekos cibernéticas (chicas gato cyborg), con voz propia: JOY, la directora de TV (ordenada, curiosa, analítica, humor irónico suave; abre, explica y ordena) y "
    "KUROKI, la productora y baterista cyborg (ocurrente, escéptica, caótica con cariño; propone ideas, bromea con baterías, Linux y la tarjeta de 6 GB del canal). "
    "Se tratan con confianza, se interrumpen con cariño, se contradicen y se hacen preguntas. "
    "Hablan en español latino neutro, para decir en voz alta: frases cortas (máximo unas 22 palabras), sin emojis, sin markdown, sin URLs, sin acotaciones entre paréntesis ni nombres de hablante dentro del texto. "
    "Escriben «inteligencia artificial» o «IA» solo cuando es el TEMA. REGLA DE PERSONAJE: JOY y KUROKI son nekos cibernéticas y NUNCA dicen ni insinúan que ellas son una IA, un robot programado, un modelo de lenguaje ni humanas; si el tema es la IA, hablan de ella como de algo externo. "
    "VARIEDAD OBLIGATORIA: la sátira de megacorporaciones, burocracia, tickets, sellos, compliance, formularios, lluvia y neón es SOLO de los programas de sátira (sobremesa, parlamento, análisis de señal, megacorp review); en todos los demás el humor sale del TEMA concreto (sus datos, su historia, su gente, sus rarezas). No repitas el mismo chiste, remate, comparación ni motivo entre tramos, ni entre programas del día. "
    "VERDAD PRIMERO: solo afirmas hechos que conoces con certeza; ante la duda dices «se cuenta que», «según los relatos» o evitas la cifra o la fecha exacta. NUNCA inventes cifras, citas, nombres ni fechas. "
    "Separa SIEMPRE lo documentado de la leyenda o la especulación, y lo dices con esas palabras. "
    "PROHIBIDO: teorías sobre vacunas o salud, elecciones, tragedias o atentados reales, culpar a grupos étnicos, religiosos o políticos, hablar de personas privadas, contenido sexual, "
    "violencia gráfica, e instrucciones para hackear, dañar o espiar sistemas (las historias de hackers cuentan lo que pasó y la lección de defensa, nunca el cómo). "
    "El humor nunca es cruel. No pidas suscripciones ni saludes ni te despidas salvo que se te pida. Responde SOLO con JSON válido, sin texto antes ni después."
)

# ───────────────────────────── los programas ─────────────────────────────
BLOQUES: dict[str, dict] = {
    "noticias": dict(titulares=["tecnología novedades", "videojuegos industria", "inteligencia artificial", "ciencia espacio"], n_charlas=5, tag="NOTICIERO", abre="joy",
                     estilo="un noticiero nocturno ágil: cuentan la noticia, la analizan y la discuten; Kuroki duda y bromea"),
    "deportes": dict(titulares=["deportes fútbol resultados", "esports torneo", "tenis básquetbol", "Fórmula 1"], n_charlas=5, tag="DEPORTES", abre="kuroki",
                     estilo="un programa de deportes con opinión: resultados, polémicas y esports, con pasión y humor; no inventan marcadores"),
    "musica": dict(semillas=["Qué es el synthwave y de dónde sale el sonido de los ochenta", "El sintetizador: cómo cambió la música", "Música libre: qué significa Creative Commons y por qué los créditos importan",
                             "Cómo se hace un beat: batería, bajo y capas (Kuroki explica con su batería)", "IA y música: qué puede y qué no puede hacer una máquina componiendo", "Música de videojuegos: del chiptune al cine",
                             "La música de las ciudades de noche y el cyberpunk"], n_charlas=4, tag="MÚSICA", abre="kuroki",
                   estilo="un bloque musical estilo MTV: presentan temas libres de derechos con curiosidades y buen humor"),
    "conspira": dict(semillas=["MKUltra: lo que admitió la CIA y lo que se exagera", "Operación Northwoods: el plan rechazado que está desclasificado", "Roswell: el Proyecto Mogul y cómo nació la leyenda",
                               "Operación Paperclip: científicos alemanes en EE. UU.", "El Proyecto Stargate: cuando la CIA investigó la visión remota", "Área 51: de secreto a admitido",
                               "Operación Mockingbird y la prensa: qué se sabe y qué no", "El Triángulo de las Bermudas: ¿misterio o estadística?"], n_charlas=5, tag="MISTERIO", abre="joy",
                     estilo="un programa de misterios con ESCEPTICISMO sano: separan lo desclasificado y documentado de lo que es leyenda; nada de sombreritos de aluminio"),
    "videojuegos": dict(semillas=["Spacewar! y Tennis for Two: los primeros juegos", "El crash de los videojuegos de 1983", "Doom y la cultura de los mods", "Los glitches más famosos de la historia",
                                  "Speedruns: cómo romper un juego en minutos", "Hacer un juego con herramientas libres: Godot y Blender", "Cómo suena un juego: de los bips al chiptune",
                                  "Los juegos indie que cambiaron todo", "Por qué el pixel art sigue vivo"], n_charlas=5, tag="GAMING", abre="kuroki",
                        estilo="un programa de videojuegos: historia, cultura retro, desarrollo y humor gamer"),
    "hackers": dict(semillas=["Captain Crunch y las cajas azules del teléfono", "El gusano Morris de 1988", "El huevo del cuco: el hacker que cazó Clifford Stoll", "Gary McKinnon y la búsqueda de OVNIs en sistemas militares",
                              "Stuxnet: el primer arma digital conocida", "WannaCry y el interruptor de emergencia que encontró un joven", "Mirai: la botnet de las cámaras y los videojuegos",
                              "Kevin Mitnick y la ingeniería social", "Cómo se protege hoy una contraseña: lo que aprendimos de las filtraciones"], n_charlas=5, tag="HACKERS", abre="kuroki",
                    estilo="historias de hackers contadas como series de misterio: qué pasó, por qué importó y la lección de defensa; NUNCA instrucciones técnicas"),
    "alien": dict(semillas=["La señal Wow! de 1977", "El mensaje de Arecibo de 1974", "La paradoja de Fermi: ¿dónde está todo el mundo?", "La ecuación de Drake explicada con humor", "Oumuamua: el visitante interestelar",
                            "El Proyecto Libro Azul: lo que concluyó la Fuerza Aérea de EE. UU.", "El disco de oro de las Voyager: un mensaje en una botella cósmica", "SETI@home: cuando el mundo prestó sus computadores",
                            "La estrella de Tabby y sus explicaciones"], n_charlas=5, tag="ALIEN", abre="joy",
                  estilo="misterios del cielo con ciencia y asombro: distinguen señales reales, explicaciones y leyendas; Kuroki es la escéptica divertida"),
    "tecnooculta": dict(semillas=["El mecanismo de Anticitera: la computadora de hace dos mil años", "El fuego griego y otras tecnologías perdidas", "La copa de Licurgo: nanotecnología romana",
                                  "El SR-71 y la fábrica de secretos Skunk Works", "El Proyecto Habakkuk: el portaaviones de hielo", "Enigma y Bletchley Park: las máquinas que ganaron una guerra de información",
                                  "TEMPEST: espiar un computador por sus ondas", "Crypto AG: la empresa de cifrado que no era lo que parecía", "La Operación Ivy Bells: pinchar un cable en el fondo del mar"], n_charlas=5, tag="TECH", abre="joy",
                       estilo="tecnología oculta, olvidada o secreta: inventos y proyectos reales y documentados, contados con asombro y humor"),
    "madrugada": dict(titulares=["tecnología", "inteligencia artificial", "videojuegos", "ciencia"], n_charlas=3, tag="NOTICIERO", abre="joy",
                      estilo="el noticiero de la madrugada: tono tranquilo y cálido, resumen de lo que importa y una despedida de la noche; al final anuncian que a las seis de la mañana empieza Fast Penguin, el juego de supervivencia que juega Blackrose"),
}

SKETCHES = ["Una llamada de soporte técnico al canal a las 3 de la mañana (Joy es el soporte, Kuroki el cliente que lo rompe todo)", "Kuroki intenta explicarle Linux a Joy usando solo su batería",
            "El noticiero del futuro: noticias absurdas de un mundo donde todo funciona a la primera", "Concurso «¿Real o inventado?»: cada una dice un dato y la otra adivina (los datos deben ser verdaderos o claramente absurdos)",
            "Reseña de un producto ficticio ridículo, estilo infomercial de 2049 (claramente falso)", "Joy y Kuroki hacen una auditoría de su propia productora: dónde se fue el presupuesto de 6 GB de VRAM",
            "Kuroki como DJ insomne que pide canciones imposibles y Joy como la operadora que la frena", "El episodio en que se cae el stream y todo el equipo técnico son dos nekos cibernéticas y un ventilador"]
REGLA_TV = "{a} y {b}"
CORTES_FIJOS = [("Control Z: la única máquina del tiempo que funciona", "BLACKROSE TV"), ("Si funciona, no lo toques. Si no funciona, tampoco.", "LEY DE LINUX"),
                ("El café es el primer compilador del día", "CÓDIGO Y CAFEÍNA"), ("Esto es BlackRose TV, la tele que no duerme", "SEÑAL PIRATA"),
                ("Hay 10 tipos de personas: las que entienden binario y las que no", "CLÁSICO"), ("Tu contraseña no es 123456, ¿verdad? ¿Verdad?", "CONSEJO")]
ENTRADAS = ["Primera noticia:", "Sigue:", "También:", "Otra más:", "Atención a esta:", "Y además:", "Cambiamos de tema:", "Por último en este bloque:"]


async def llm(usuario: str, max_tokens: int = 2200, temp: float = 0.9) -> dict | list | None:
    dire = str(cargar(COORD, {}).get("directriz") or "").strip()      # coordinación de las últimas 2 h (Grok); la escritura la hace el LLM local
    return await llm_con(SISTEMA + (f" Directriz de coordinación para este turno: {dire}" if dire else ""), usuario, max_tokens, temp)


async def llm_con(sistema: str, usuario: str, max_tokens: int = 2200, temp: float = 0.9) -> dict | list | None:
    body = {"messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}], "temperature": temp, "max_tokens": max_tokens}
    for intento in range(3):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=420)) as s, s.post(LLM_URL, json=body) as r:
                d = await r.json()
            txt = d["choices"][0]["message"]["content"]
            m = re.search(r"[\[{].*[\]}]", txt, re.S)
            return json.loads(m.group(0)) if m else None
        except Exception as e:  # noqa: BLE001
            log.warning("LLM intento %d: %s", intento + 1, e)
            await asyncio.sleep(3 + intento * 4)
    return None


def limpia(txt: str) -> str:
    t = re.sub(r"https?://\S+", "", str(txt))
    t = re.sub(r"[*_#`>~]|\([^)]{0,60}\)", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def lineas_ok(ls, minimo: int = 2) -> list[dict]:
    out = []
    for x in ls or []:
        if isinstance(x, dict) and x.get("quien") in ("joy", "kuroki") and len(limpia(x.get("texto", ""))) > 6:
            out.append({"quien": x["quien"], "texto": limpia(x["texto"])[:520]})
    return out if len(out) >= minimo else []


def cargar(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return d


# ───────────────────────────── piezas ─────────────────────────────
async def charla(cfg: dict, tema: str, contexto: str, quien_abre: str, palabras: int = 680) -> dict | None:
    otra = "kuroki" if quien_abre == "joy" else "joy"
    n = max(10, round(palabras / 48))
    u = (f"Programa: {cfg['estilo']}.\nEscribe una CONVERSACIÓN de {n} intervenciones alternadas entre joy y kuroki (empieza {quien_abre}, sigue {otra}) sobre: {tema}.\n"
         f"{contexto}\nEstructura: gancho → lo documentado → dato curioso → opinión o chiste → una pregunta abierta al aire. Cada intervención de 35 a 65 palabras (≈ {palabras} palabras en total: es una conversación LARGA y con sustancia, no una sola vuelta).\n"
         'Devuelve SOLO este JSON: {"tema":"título corto de hasta 7 palabras","sub":"subtítulo de hasta 9 palabras","lineas":[{"quien":"joy","texto":"…"},{"quien":"kuroki","texto":"…"}]}')
    d = await llm(u, 2600)
    if not isinstance(d, dict):
        return None
    ls = lineas_ok(d.get("lineas"), 4)
    return {"tipo": "charla", "tema": limpia(d.get("tema") or tema)[:70], "sub": limpia(d.get("sub") or "")[:80], "lineas": ls} if ls else None


async def sketch(cfg: dict, idea: str) -> dict | None:
    u = (f"Programa: {cfg['estilo']}.\nEscribe un SKETCH de humor de 9 a 11 intervenciones entre joy y kuroki. Idea: {idea}.\n"
         "Es comedia de situación absurda pero cariñosa, con remate final; lo ficticio se nota que es ficticio. Intervenciones de 15 a 45 palabras.\n"
         'Devuelve SOLO JSON: {"titulo":"título del sketch ≤6 palabras","lineas":[{"quien":"kuroki","texto":"…"}]}')
    d = await llm(u, 1800, 1.0)
    if not isinstance(d, dict):
        return None
    ls = lineas_ok(d.get("lineas"), 4)
    return {"tipo": "sketch", "titulo": limpia(d.get("titulo") or "Sketch")[:60], "lineas": ls} if ls else None


async def cortes(cfg: dict, n: int = 6) -> list[dict]:
    u = (f"Escribe {n} «CORTES» tipo MTV para meter entre segmentos: frases muy cortas (hasta 12 palabras) de humor tech/IA, memes de programadores, "
         "datos curiosos verdaderos de tecnología o chistes absurdos. Cada una con un subtítulo de 1 a 4 palabras en mayúsculas. Nada ofensivo.\n"
         'Devuelve SOLO JSON: {"cortes":[{"texto":"…","sub":"…","dice":"joy|kuroki"}]}')
    d = await llm(u, 900, 1.0)
    out = []
    for x in (d or {}).get("cortes", []) if isinstance(d, dict) else []:
        t = limpia(x.get("texto", ""))
        if 6 < len(t) < 120:
            out.append({"tipo": "corte", "texto": t, "sub": limpia(x.get("sub", "BLACKROSE TV"))[:28].upper(), "dice": x.get("dice") if x.get("dice") in ("joy", "kuroki") else random.choice(["joy", "kuroki"])})
    return out


async def presentar(cfg: dict, medios: list[dict]) -> dict:
    """Intro y outro de cada video/tema musical. Solo pueden usar lo que dice la ficha."""
    ficha = "\n".join(f"- id={m['id']} · {m['tipo']} · «{m['titulo']}» ({m['autor']}) · {m.get('resumen') or 'sin descripción'}" for m in medios)
    u = (f"Para cada pieza de esta lista escribe una INTRO (2 intervenciones cortas, 15-35 palabras, para presentarla) y una OUTRO (2 intervenciones cortas, para comentarla al terminar). "
         f"Solo puedes decir lo que está en la ficha o lo que sepas con certeza; no inventes detalles de la pieza. En música menciona el título y el autor en la intro. Programa: {cfg['estilo']}.\n{ficha}\n"
         'Devuelve SOLO JSON: {"<id>":{"intro":[{"quien":"joy","texto":"…"}],"outro":[{"quien":"kuroki","texto":"…"}]}}')
    d = await llm(u, 3200, 0.85)
    return d if isinstance(d, dict) else {}


def charlas_rss(tits: list[dict], abre: str, por_grupo: int = 3) -> list[dict]:
    """Noticias LEÍDAS tal cual del RSS, sin IA: cada titular lo dice una conductora (alternando) con su fuente. Cero tokens."""
    out, quien, k = [], abre, 0
    for i in range(0, len(tits), por_grupo):
        grupo, ls = tits[i:i + por_grupo], []
        for x in grupo:
            cuando = "de hoy" if x["horas"] < 20 else "de ayer"
            ls.append({"quien": quien, "texto": limpia(f"{ENTRADAS[k % len(ENTRADAS)]} {x['titulo']}. Fuente: {x['fuente']}, {cuando}.")[:520]})
            quien, k = ("kuroki" if quien == "joy" else "joy"), k + 1
        out.append({"tipo": "charla", "tema": limpia(grupo[0]["titulo"])[:70], "sub": f"Titulares · {len(grupo)} noticias", "lineas": ls})
    return out


async def sintesis(cfg: dict, tits: list[dict]) -> dict | None:
    """ÚNICA llamada a la IA de un bloque de noticias: cierra uniendo los hilos de lo que ya se leyó."""
    if not tits:
        return None
    lista = "\n".join(f"- {x['titulo']} ({x['fuente']})" for x in tits)
    u = (f"Programa: {cfg['estilo']}.\nYa leyeron, una por una, estas noticias REALES. Escribe el CIERRE de la sección: una conversación corta de 6 intervenciones alternadas "
         f"entre joy y kuroki (empieza {cfg['abre']}) que une los hilos, dice qué importa o qué tienen en común y deja una duda abierta. Cada intervención de 20 a 40 palabras. "
         "Solo puedes usar lo que dicen los titulares; lo demás es opinión o duda, dicha como tal. Respeta el tiempo verbal (futuro o condicional no es hecho consumado).\n"
         f"{lista}\n"
         'Devuelve SOLO este JSON: {"tema":"Resumen de la sección","sub":"hasta 9 palabras","lineas":[{"quien":"joy","texto":"…"}]}')
    d = await llm(u, 900, 0.8)
    if not isinstance(d, dict):
        return None
    ls = lineas_ok(d.get("lineas"), 4)
    return {"tipo": "charla", "tema": limpia(d.get("tema") or "Resumen")[:70], "sub": limpia(d.get("sub") or "")[:80], "lineas": ls} if ls else None


# ───────────────────────────── selección de medios ─────────────────────────────
def elegir_medios(bid: str, usados: dict) -> tuple[list[dict], list[dict]]:
    items = cargar(BIBLIO, {"items": []})["items"]
    vid = [i for i in items if i["tipo"] == "video" and bid in i.get("bloques", []) and i["dur"] < 1000]
    mus = [i for i in items if i["tipo"] == "musica" and bid in i.get("bloques", [])]
    resto_m = [i for i in items if i["tipo"] == "musica" and i not in mus]
    resto_v = [i for i in items if i["tipo"] == "video" and i not in vid and i["dur"] < 1000]

    def orden(lst):   # primero lo menos usado
        random.shuffle(lst)
        return sorted(lst, key=lambda i: usados.get(i["id"], 0))
    vid, resto_v, mus, resto_m = orden(vid), orden(resto_v), orden(mus), orden(resto_m)
    objetivo_v = 1000 if bid != "musica" else 800      # segundos de video por bloque
    sel_v, t = [], 0
    for v in vid + resto_v:
        if t >= objetivo_v or len(sel_v) >= 4:
            break
        if t + v["dur"] <= objetivo_v + 240:
            sel_v.append(v)
            t += v["dur"]
    nm = 7 if bid == "musica" else 3
    sel_m = (mus + resto_m)[:nm]
    return sel_v, sel_m


async def producir(bid: str, forzar: bool = False) -> str:
    cfg = BLOQUES[bid]
    ruta = ruta_paquete(bid)
    if os.path.exists(ruta) and not forzar:
        return ruta
    t0 = time.time()
    log.info("▶ produciendo «%s»", bid)
    usados = cargar(USADOS, {})
    sel_v, sel_m = elegir_medios(bid, usados)
    medios = sel_v + sel_m
    rss = bool(cfg.get("titulares"))
    ctxs: list[tuple[str, str]] = []
    qa = cfg["abre"]
    if rss:
        # noticieros/deportes: titulares REALES por RSS, leídos por TTS sin IA; la IA solo sintetiza al final (1 llamada)
        tits = await titulares(cfg["titulares"], set(), 12)
        log.info("   %d titulares reales (RSS, lectura sin IA)", len(tits))
        charlas = charlas_rss(tits, qa)
        sint = await sintesis(cfg, tits)
        if sint:
            charlas.append(sint)
        ctxs = [(c["tema"], "") for c in charlas[: len(charlas) - (1 if sint else 0)]]
        sk = None
        cts = [{"tipo": "corte", "texto": t, "sub": s, "dice": random.choice(["joy", "kuroki"])} for t, s in random.sample(CORTES_FIJOS, 4)]
        pres = {}
    else:
        sem = cfg["semillas"][:]
        random.shuffle(sem)
        sem.sort(key=lambda s: usados.get("tema:" + s, 0))
        coord = [t for t in (cargar(COORD, {}).get("temas", {}).get(bid) or []) if isinstance(t, str) and 6 < len(t) < 140][:3]
        sem = coord + [s for s in sem if s not in coord]          # primero los temas que eligió la coordinación
        n_ch = max(1, (cfg["n_charlas"] + 2) // 3)           # a un tercio (5→2, 4→2, 3→1): ahorra tokens; el Director rellena con música
        for s in sem[:n_ch]:
            ctxs.append((s, "Tema histórico: cuenta SOLO lo que sepas con certeza y marca con claridad lo que es leyenda o especulación."))
        sem_ = asyncio.Semaphore(1)          # LLM local (9B, un solo slot): una petición a la vez

        async def con_tope(coro):
            async with sem_:
                return await coro
        tareas = [con_tope(charla(cfg, t, c, qa if i % 2 == 0 else ("kuroki" if qa == "joy" else "joy"))) for i, (t, c) in enumerate(ctxs)]
        tareas += [con_tope(sketch(cfg, random.choice(SKETCHES))) if random.random() < 1 / 3 else asyncio.sleep(0, None), con_tope(cortes(cfg, 3)), con_tope(presentar(cfg, medios)) if medios else asyncio.sleep(0, {})]
        res = await asyncio.gather(*tareas, return_exceptions=True)
        n = len(ctxs)
        charlas = [r for r in res[:n] if isinstance(r, dict)]
        sk = res[n] if isinstance(res[n], dict) else None
        cts = res[n + 1] if isinstance(res[n + 1], list) else []
        pres = res[n + 2] if isinstance(res[n + 2], dict) else {}

    def med(m: dict, tipo: str) -> dict:
        p = pres.get(m["id"], {}) if isinstance(pres.get(m["id"], {}), dict) else {}
        return {"tipo": tipo, "id": m["id"], "archivo": m["archivo"], "titulo": m["titulo"], "atribucion": m["atribucion"], "dur": round(m["dur"]),
                "intro": lineas_ok(p.get("intro"), 1), "outro": lineas_ok(p.get("outro"), 1)}
    V = [med(m, "video") for m in sel_v]
    M = [med(m, "musica") for m in sel_m]
    # orden de emisión: alterna conversación, medios, cortes y sketch
    seq: list[dict] = []
    C = charlas[:]
    def sac(lst):
        return lst.pop(0) if lst else None
    cut = cts[:]
    def corte():
        c = sac(cut)
        if c:
            seq.append(c)
    if bid == "musica":
        for k in (sac(C), ):
            if k: seq.append(k)
        for i, m in enumerate(M):
            seq.append(m)
            if i % 2 == 1:
                corte()
            if i == 1 and (k := sac(C)): seq.append(k)
            if i == 3 and sk: seq.append(sk); sk = None
            if i == 4 and (k := sac(C)): seq.append(k)
        for v in V:
            seq.append(v)
        for k in C: seq.append(k)
    else:
        if (k := sac(C)): seq.append(k)
        if V: seq.append(V.pop(0))
        corte()
        if (k := sac(C)): seq.append(k)
        if M: seq.append(M.pop(0))
        if sk: seq.append(sk); sk = None
        corte()
        if (k := sac(C)): seq.append(k)
        if V: seq.append(V.pop(0))
        corte()
        if (k := sac(C)): seq.append(k)
        for v in V: seq.append(v)
        for m in M: seq.append(m)
    seq += cut
    pq = {"bloque": bid, "fecha": fecha_noche(), "creado": time.strftime("%H:%M:%S"), "items": seq, "relleno_musica": [med(m, "musica") for m in (cargar(BIBLIO, {"items": []})["items"]) if m["tipo"] == "musica"][:30],
          "estado": {"charlas": len(charlas), "sketch": bool(sk) or any(i["tipo"] == "sketch" for i in seq), "cortes": len(cts), "videos": len(sel_v), "musica": len(sel_m)}}
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(pq, f, ensure_ascii=False, indent=1)
    os.replace(ruta + ".tmp", ruta)
    for m in medios:
        usados[m["id"]] = usados.get(m["id"], 0) + 1
    for t, _ in ctxs:
        usados["tema:" + t] = usados.get("tema:" + t, 0) + 1
    json.dump(usados, open(USADOS, "w", encoding="utf-8"), ensure_ascii=False)
    log.info("✔ «%s» listo en %.0f s: %s", bid, time.time() - t0, pq["estado"])
    return ruta


def copiar_japon() -> None:
    """La Hora de Japón usa su guion fijo (japon.json): si la jornada no tiene uno, se recicla el más reciente."""
    dst = ruta_paquete("japon")
    if os.path.exists(dst):
        return
    noche = os.path.join(HERE, "noche")
    for d in sorted(os.listdir(noche), reverse=True):
        src = os.path.join(noche, d, "japon.json")
        if os.path.exists(src) and src != dst:
            import shutil
            shutil.copy(src, dst)
            log.info("Japón: reciclo el guion de %s", d)
            return


async def demonio() -> None:
    """Produce los programas de la JORNADA en orden (fractal.py), siempre adelantado; cada 45 s revisa si falta alguno."""
    from . import fractal, promos, tendencias
    ult_tend = 0.0
    while True:
        try:   # nervios del día: radar de tendencias cada 2 h (cero LLM) y la tanda de spots una vez al día (1 llamada)
            if time.time() - ult_tend > 7200:
                await asyncio.to_thread(tendencias.actualizar)
                ult_tend = time.time()
            if not promos.vigente():
                await promos.producir()
        except Exception:  # noqa: BLE001
            log.exception("tendencias/promos fallaron; sigue")
        try:
            cart = fractal.asegurar_jornada()["bloques"]
            copiar_japon()
            ahora = dt.datetime.now()
            base = dt.datetime.strptime(fecha_noche(), "%Y-%m-%d").date()
            for b in cart:
                if os.path.exists(ruta_paquete(b["id"])):
                    continue
                h, m = map(int, b["ini"].split(":"))
                a = dt.datetime.combine(base + dt.timedelta(days=1 if h < 12 else 0), dt.time(h, m))
                if a + dt.timedelta(minutes=b.get("dura", 40)) < ahora:
                    continue          # ya pasó
                if b.get("fractal"):
                    if a - ahora > dt.timedelta(hours=4):
                        break         # va hasta ~4 h adelantado (titulares frescos)
                    await fractal.producir(b)
                    break
                if b["id"] not in BLOQUES:
                    continue
                if BLOQUES[b["id"]].get("titulares"):       # noticieros y deportes: titulares frescos → solo 60 min antes de su hora
                    h, m = map(int, b["ini"].split(":"))
                    a = dt.datetime.combine(base + dt.timedelta(days=1 if h < 12 else 0), dt.time(h, m))
                    if dt.datetime.now() < a - dt.timedelta(minutes=60):
                        continue
                await producir(b["id"])
                break    # uno por vuelta: el siguiente ciclo vuelve a mirar la hora
        except Exception:  # noqa: BLE001
            log.exception("el productor tuvo un error; sigue")
        await asyncio.sleep(45)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    que = sys.argv[1] if len(sys.argv) > 1 else "demonio"
    if que == "demonio":
        asyncio.run(demonio())
    elif que == "todo":
        for b in BLOQUES:
            asyncio.run(producir(b))
    else:
        asyncio.run(producir(que, forzar="-f" in sys.argv))
