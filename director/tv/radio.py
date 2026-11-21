"""RADIO BLACKROSE 2049: la biblioteca musical sale de playlists SIN COPYRIGHT de YouTube (pedido 2026-11-20; reemplaza a los MIDI).
Los temas los baja director/web/tv/media/yt/bajar.sh (solo audio + miniatura + info.json). Cada tema lleva su crédito en pantalla.
  temas(genero=None)  → [{tipo:"musica", archivo:"yt/<g>/<id>.m4a", titulo, atribucion, dur, img, genero, id}]
"""
from __future__ import annotations

import glob
import json
import os
import random
import re


def limpio(t: str) -> str:
    """«Cyberpunk Gaming Trailer by Infraction [No Copyright Music] / Just Evil» → «Just Evil · Infraction»-ish: fuera etiquetas de copyright."""
    t = re.sub(r"[\[\(【][^\]\)】]*(copyright|ncs|release|royalty|free|music|mix|visualizer|official)[^\]\)】]*[\]\)】]", "", t, flags=re.I)
    t = re.sub(r"\b(no copyright( music)?|copyright free( music)?|royalty free( music)?|ncs release|free download)\b", "", t, flags=re.I)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", t)
    t = re.sub(r"\|\s*(twitch|stream|gaming|background)[^|]*$", "", t, flags=re.I)
    t = re.sub(r"[|/]{1,2}\s*$|^\s*[|/-]+", "", re.sub(r"\s{2,}", " ", t)).strip(" -|/·")
    return t or "Tema sin título"

HERE = os.path.dirname(os.path.abspath(__file__))
YT = os.path.join(HERE, "..", "web", "tv", "media", "yt")
GENEROS = {"cyberpunk": "CYBERPUNK", "phonk": "PHONK", "darktechno": "DARK TECHNO", "techno": "TECHNO", "coding": "CODING", "synthwave": "SYNTHWAVE", "darksynth": "DARK SYNTHWAVE", "citypop": "CITY POP JAPÓN"}
# qué suena en cada programa (el resto: todo)
GUSTO = {"noticias": ["coding", "synthwave", "techno"], "analisis": ["darktechno", "coding"], "politica": ["darktechno", "cyberpunk"], "megacorp": ["synthwave", "phonk"],
         "sobremesa": ["citypop", "synthwave"], "hackers": ["darktechno", "coding"], "linux": ["coding"], "videojuegos": ["phonk", "synthwave"], "deportes": ["phonk"],
         "conspira": ["darktechno"], "alien": ["darktechno", "synthwave"], "teatro": ["synthwave"]}


def temas(genero: str | list[str] | None = None) -> list[dict]:
    gs = [genero] if isinstance(genero, str) else (genero or list(GENEROS))
    out = []
    for g in gs:
        for f in glob.glob(os.path.join(YT, g, "*.info.json")):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            base = f[: -len(".info.json")]
            audio = next((base + e for e in (".m4a", ".webm", ".opus", ".mp3") if os.path.exists(base + e)), None)
            if not audio or not d.get("duration"):
                continue
            canal = d.get("channel") or d.get("uploader") or "YouTube"
            tit = limpio(d.get("track") or d.get("title") or "Tema")
            video = base + ".mp4" if os.path.exists(base + ".mp4") else None     # con video (como en YouTube) se ve a pantalla grande
            out.append({"tipo": "video" if video else "musica", "radio": True, "id": "yt_" + d["id"], "archivo": os.path.relpath(video or audio, os.path.join(YT, "..")), "titulo": tit[:90], "audio": os.path.relpath(audio, os.path.join(YT, "..")),
                        "atribucion": f"Música: «{tit[:70]}» · {canal} · sin copyright (YouTube)", "dur": round(d["duration"]), "genero": GENEROS.get(g, g.upper()),
                        "img": ("/tv/media/" + os.path.relpath(base + ".jpg", os.path.join(YT, ".."))) if os.path.exists(base + ".jpg") else None,
                        "intro": [], "outro": []})
    return out


def para_programa(pid: str, n: int, usados: dict, rnd: random.Random | None = None) -> list[dict]:
    rnd = rnd or random.Random()
    ts = temas(GUSTO.get(pid)) or temas()
    rnd.shuffle(ts)
    s = sonados()
    ts.sort(key=lambda t: (usados.get(t["id"], 0), s.get(t["id"], 0)))
    return ts[:n]


SONADOS = os.path.join(HERE, "radio_sonados.json")     # historial persistente: lo que ya sonó no se repite (pedido 20-nov)


def sonados() -> dict:
    try:
        return json.load(open(SONADOS, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def marcar(tid: str) -> None:
    import time
    d = sonados()
    d[tid] = time.time()
    d = dict(sorted(d.items(), key=lambda x: x[1])[-150:])
    tmp = SONADOS + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, SONADOS)


def frescos(ts: list[dict]) -> list[dict]:
    """Primero lo que nunca sonó, después lo que sonó hace más tiempo."""
    s = sonados()
    return sorted(ts, key=lambda t: s.get(t["id"], 0))
