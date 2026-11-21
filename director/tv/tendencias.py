"""TENDENCIAS de BlackRose TV: el radar de lo que se habla hoy. Puro nervio: CERO LLM.

  .venv/bin/python -m director.tv.tendencias        (lo corre brtv-tendencias.timer cada 2 h)

Lee Google Trends (Chile, México, Japón; RSS público, sin clave), descarta por reglas lo que la línea editorial no toca
(tragedias, accidentes, crímenes, política electoral) y clasifica cada tendencia en un programa del catálogo por palabras
clave. Escribe tv/tendencias.json:
  {"t": …, "por_programa": {pid: [{"termino", "contexto", "geo", "trafico"}]}, "descartadas": n}
El fractal las usa sin pedir nada al LLM: en programas con RSS, el término se suma a las consultas de Google News (la
noticia real la trae el RSS); en los demás, entra como semilla «Tendencia de hoy: …» (la investiga el 9B como cualquier otra).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

log = logging.getLogger("tendencias")
HERE = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(HERE, "tendencias.json")
GEOS = {"CL": "Chile", "MX": "México", "JP": "Japón"}
NS = {"ht": "https://trends.google.com/trending/rss"}

# Línea editorial (tv-noche-canal): nada de tragedias, crímenes, salud dudosa ni elecciones.
FUERA = re.compile(r"(muert|muere|fallec|asesin|homicid|choque|accident|incendi|victim|herid|tirote|crimen|robo|detenid|carabiner|polic[ií]a|"
                   r"eleccion|elector|candidat|ministr|president|gobiern|senad|diputad|partido (politico|republicano)|plebiscit|votaci|"
                   r"sismo|terremot|tsunami|inundaci|aluvi|desapareci|secuestr|violaci|abuso|suicid|cancer|vacuna|"
                   r"殺|事故|死|逮捕|選挙|地震)", re.I)

# Programa ← palabras clave (sobre término + titulares de la tendencia, normalizados). El orden importa: gana la primera.
CLASES: list[tuple[str, str]] = [
    ("videojuegos", r"\b(juego|videojuego|gamer|gaming|nintendo|switch|playstation|ps5|xbox|game pass|steam|pokemon|zelda|mario|gta|fortnite|"
                    r"minecraft|roblox|valorant|league of legends|esports?|twitch|capcom|sega|square enix|elden|call of duty|ゲーム|任天堂|ポケモン|ウマ娘|メンテ|ガチャ)\b"),
    ("ia", r"\b(ia|inteligencia artificial|chatgpt|openai|gemini|claude|copilot|deepseek|llm|robot|robotica|humanoide|生成ai|人工知能)\b"),
    ("tecnologia", r"\b(iphone|apple|samsung|android|google|microsoft|windows|linux|nvidia|amd|intel|chip|procesador|celular|smartphone|"
                   r"internet|wifi|5g|ciberataque|hackeo|whatsapp|instagram|tiktok|youtube|tesla|spacex|starlink|スマホ)\b"),
    ("ciencia", r"\b(nasa|esa|cometa|eclipse|luna|marte|asteroide|telescopio|astronom|cientific|descubrimiento|fosil|dinosaurio|aurora|meteor|宇宙)\b"),
    ("musica", r"\b(concierto|album|cancion|cantante|banda|festival|gira|tour|spotify|grammy|reggaeton|kpop|rock|lollapalooza|vina|音楽|ライブ)\b"),
    ("deportes", r"\b(futbol|gol|partido|liga|copa|mundial|seleccion|club|campeonato|anfp|colo.colo|universidad de chile|u de chile|real madrid|"
                 r"barcelona|messi|ronaldo|bielsa|dt|entrenador|tecnico|f1|formula 1|gran premio|tenis|nba|nfl|boxeo|ufc|olimp|サッカー|野球)\b"),
]
CLASES_C = [(p, re.compile(r, re.I)) for p, r in CLASES]


def _n(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def leer(geo: str) -> list[dict]:
    req = urllib.request.Request(f"https://trends.google.com/trending/rss?geo={geo}", headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) BlackRoseTV"})
    raiz = ET.fromstring(urllib.request.urlopen(req, timeout=20).read())
    out = []
    for it in raiz.iter("item"):
        noticias = [(n.findtext("ht:news_item_title", namespaces=NS) or "").strip() for n in it.findall("ht:news_item", NS)]
        out.append({"termino": (it.findtext("title") or "").strip(), "contexto": next((x for x in noticias if x), "")[:140],
                    "noticias": noticias, "geo": geo, "trafico": (it.findtext("ht:approx_traffic", namespaces=NS) or "").strip()})
    return out


def clasificar(t: dict) -> str | None:
    texto = _n(" ".join([t["termino"], *t["noticias"][:2]]))
    if FUERA.search(_n(" ".join([t["termino"], *t["noticias"]]))):
        return None
    for pid, rx in CLASES_C:
        if rx.search(texto):
            return pid
    return ""      # tendencia limpia pero sin programa: queda en «otras»


def actualizar() -> dict:
    por: dict[str, list[dict]] = {}
    desc = 0
    vistos = set()
    for geo in GEOS:
        try:
            ts = leer(geo)
        except Exception as e:  # noqa: BLE001
            log.warning("trends %s: %s", geo, e)
            continue
        for t in ts:
            k = _n(t["termino"])
            if not t["termino"] or k in vistos:
                continue
            vistos.add(k)
            pid = clasificar(t)
            if pid is None:
                desc += 1
                continue
            t.pop("noticias", None)
            por.setdefault(pid or "otras", []).append(t)
    if not por and os.path.exists(SALIDA):      # sin red: se conserva el radar anterior (mejor viejo que vacío)
        log.warning("sin tendencias nuevas: conservo las anteriores")
        return json.load(open(SALIDA, encoding="utf-8"))
    d = {"t": time.strftime("%Y-%m-%d %H:%M"), "por_programa": por, "descartadas": desc}
    with open(SALIDA + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(SALIDA + ".tmp", SALIDA)
    log.info("tendencias: %s · descartadas %d", {k: len(v) for k, v in por.items()}, desc)
    return d


def de_programa(pid: str, n: int = 2, max_horas: float = 8) -> list[dict]:
    """Las n tendencias más fuertes del programa, si el radar es reciente (lo usa el fractal)."""
    try:
        d = json.load(open(SALIDA, encoding="utf-8"))
        if time.time() - time.mktime(time.strptime(d["t"], "%Y-%m-%d %H:%M")) > max_horas * 3600:
            return []
    except (OSError, ValueError, KeyError):
        return []
    trafico = lambda t: int(re.sub(r"\D", "", t.get("trafico") or "0") or 0)  # noqa: E731
    return sorted(d.get("por_programa", {}).get(pid, []), key=trafico, reverse=True)[:n]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    r = actualizar()
    for pid, ts in r["por_programa"].items():
        print(f"{pid:12}", " · ".join(f"{t['termino']} ({t['geo']})" for t in ts[:6]))
    print("descartadas por línea editorial:", r["descartadas"])
