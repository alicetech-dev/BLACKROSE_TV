"""Interludios «sala de control» de BlackRose TV: noticias CON FOTO, tus últimos videos de YouTube, tendencias y pedidos de ayuda.
GRATIS y LOCAL: RSS/páginas públicas + UNA sola llamada al cerebro local (:8087, 4B) cada ~100 min; si el LLM falla salen plantillas.
  · videos: feed RSS público del canal de YouTube (sin API ni claves)      · noticias: BBC Mundo / Xataka (foto del feed o og:image)
  · tendencias: Google Trends Chile (RSS) + el radar de X de x_manager SI está fresco (<3 días)
  · ayuda: pide seguir/compartir/ideas (y donar SOLO si pones `donar` en apoyo_config.json)
El director llama `siguiente()` en un corte «sala»; apoyo.json guarda el stock y apoyo_estado.json qué se usó.
  .venv/bin/python -m director.tv.apoyo producir|ver
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

log = logging.getLogger("apoyo")
HERE = os.path.dirname(os.path.abspath(__file__))
MEDIOS = os.path.join(HERE, "medios")
OUT, EST, CFG = (os.path.join(HERE, f) for f in ("apoyo.json", "apoyo_estado.json", "apoyo_config.json"))
RADAR_X = os.path.expanduser("~/x_manager/data/radar_candidatos.json")
UA = {"User-Agent": "Mozilla/5.0 (BlackRoseTV)"}
VIGENCIA = 100 * 60
CFG0 = {"youtube_channel_id": "UCqJZgSPPgvhE2cFpn3t0iBA", "youtube": "@barbieblackrose", "twitch": "barbieblackrose", "x": "@BarbieBlackRose",
        "donar": None, "cada_ayuda_min": 25, "pais": "CL"}
FEEDS = [("BBC Mundo", "https://feeds.bbci.co.uk/mundo/rss.xml"), ("Xataka", "https://www.xataka.com/feedburner.xml")]
NS = {"media": "http://search.yahoo.com/mrss/", "a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "ht": "https://trends.google.com/trending/rss"}
_lock = asyncio.Lock()


def cargar(p, d):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return d


def cfg() -> dict:
    return {**CFG0, **cargar(CFG, {})}


def get(url: str, t: int = 15, binario: bool = False, tope: int = 4_000_000):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t) as r:
        b = r.read(tope)
    return b if binario else b.decode("utf-8", "replace")


def imagen(url: str | None) -> str | None:
    """Baja una foto a medios/ (≤3 MB, solo imágenes) y devuelve su ruta pública /medios/<archivo>."""
    if not url or not url.startswith("http"):
        return None
    os.makedirs(MEDIOS, exist_ok=True)
    f = hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg"
    if not os.path.exists(os.path.join(MEDIOS, f)):
        try:
            b = get(url, 15, True, 3_000_000)
            if b[:3] != b"\xff\xd8\xff" and b[:4] != b"\x89PNG" and b[:4] != b"RIFF":
                return None
            open(os.path.join(MEDIOS, f), "wb").write(b)
        except Exception as e:  # noqa: BLE001
            log.warning("foto %s: %s", url[:60], e)
            return None
    return "/medios/" + f


def videos(c: dict, n: int = 3) -> list[dict]:
    try:
        x = ET.fromstring(get(f"https://www.youtube.com/feeds/videos.xml?channel_id={c['youtube_channel_id']}"))
        return [{"titulo": e.findtext("a:title", "", NS), "id": e.findtext("yt:videoId", "", NS), "pub": e.findtext("a:published", "", NS)[:10],
                 "img": f"https://i.ytimg.com/vi/{e.findtext('yt:videoId', '', NS)}/hqdefault.jpg"} for e in x.findall("a:entry", NS)[:n]]
    except Exception as e:  # noqa: BLE001
        log.warning("youtube: %s", e)
        return []


def noticias(n: int = 4) -> list[dict]:
    out = []
    for fuente, url in FEEDS:
        try:
            for it in ET.fromstring(get(url)).iter("item"):
                if len([o for o in out if o["fuente"] == fuente]) >= 3:
                    break
                t = re.sub(r"\s+", " ", (it.findtext("title") or "")).strip()
                th = it.find("media:thumbnail", NS) if it.find("media:thumbnail", NS) is not None else it.find("media:content", NS)
                img = th.get("url") if th is not None else None
                if img and "bbci.co.uk" in img:
                    img = re.sub(r"/ws/\d+/", "/ws/800/", img)
                if not img:                                                # sin foto en el feed: og:image de la nota
                    try:
                        m = re.search(r'property="og:image"\s+content="([^"]+)"', get(it.findtext("link") or "", 10, False, 120_000))
                        img = m.group(1) if m else None
                    except Exception:  # noqa: BLE001
                        img = None
                if t and img:
                    out.append({"titulo": t, "fuente": fuente, "img": img})
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s: %s", fuente, e)
    random.shuffle(out)
    return out[:n]


def tendencias(c: dict, n: int = 5) -> list[dict]:
    out = []
    try:
        for it in ET.fromstring(get(f"https://trends.google.com/trending/rss?geo={c['pais']}")).iter("item"):
            out.append({"tema": it.findtext("title") or "", "img": it.findtext("ht:picture", None, NS), "origen": "Google Trends"})
    except Exception as e:  # noqa: BLE001
        log.warning("trends: %s", e)
    try:                                                                    # el radar de X de ella, solo si es reciente (lo corre x_manager)
        if time.time() - os.path.getmtime(RADAR_X) < 3 * 86400:
            for p in cargar(RADAR_X, {}).get("posts", [])[:30]:
                for h in re.findall(r"#(\w{4,})", p.get("text", "")):
                    out.append({"tema": "#" + h, "img": None, "origen": "radar de X"})
    except OSError:
        pass
    vistos, res = set(), []
    for t in out:
        k = t["tema"].lower()
        if k and k not in vistos:
            vistos.add(k); res.append(t)
    return res[:n]


# ───────────── guiones: UNA llamada al cerebro local; si falla, plantillas ─────────────
def ayudas(c: dict) -> list[list]:
    v = [[["joy", "Este canal funciona gratis, con inteligencia artificial local en el computador de Alice, las veinticuatro horas. Si te gusta, sígueme en Twitch y compártelo con alguien."],
          ["kuroki", "Y deja una idea en el chat: lo que más pidan, lo convertimos en programa."]],
         [["kuroki", "Ayúdanos a seguir al aire: suscríbete al canal de YouTube de Alice y activa la campanita."],
          ["joy", "Cada suscripción, cada like y cada compartida nos mantiene prendidas. Gracias, de verdad."]],
         [["joy", "Misión de la noche: que este canal siga solo, gratis y en vivo. Y tú eres parte de la misión."],
          ["kuroki", "Quédate un ratito más, escribe en el chat y trae a un amigo. Así crecemos sin gastar un peso."]],
         [["kuroki", f"Alice también está en X como {c['x']}. Síguela para enterarte de los próximos programas."],
          ["joy", "Y cuéntale qué contenido quieres ver aquí. Nosotras lo hacemos realidad, con electricidad y cariño."]]]
    if c.get("donar"):
        v.append([["joy", f"Si quieres darle un empujón extra al canal, hay un enlace de apoyo en la descripción: {c['donar']}."], ["kuroki", "Es totalmente opcional. Con que te quedes, ya nos haces el día."]])
    return v


def plantillas(vs, ns, ts, c) -> list[dict]:
    out = []
    for v in vs[:2]:
        out.append({"clase": "video", "titulo": v["titulo"], "img": v["img"], "credito": "Nuevo en YouTube · " + c["youtube"],
                    "lineas": [["joy", f"Atención: hay un video del canal de Alice: «{v['titulo']}». Búscalo en YouTube."], ["kuroki", "Míralo, déjale un like y comenta. Eso la ayuda un montón."]]})
    for n in ns[:3]:
        out.append({"clase": "noticia", "titulo": n["titulo"], "img": n["img"], "credito": "Foto y nota: " + n["fuente"],
                    "lineas": [["joy", f"Nota con foto de {n['fuente']}: {n['titulo']}."], ["kuroki", "Ojo: es lo que dice el titular. ¿Tú qué opinas? Cuéntanos en el chat."]]})
    for t in ts[:2]:
        out.append({"clase": "tendencia", "titulo": t["tema"], "img": t["img"], "credito": "Tendencia · " + t["origen"],
                    "lineas": [["joy", f"Lo que más se está buscando ahora: {t['tema']}."], ["kuroki", "¿Hacemos un programa sobre eso? Escríbelo en el chat y lo consideramos."]]})
    for a in ayudas(c):
        out.append({"clase": "ayuda", "titulo": "AYÚDANOS A SEGUIR AL AIRE", "img": None, "credito": f"Twitch {c['twitch']} · YouTube {c['youtube']} · X {c['x']}", "lineas": a})
    return out


SIS = ("Eres el guionista de BlackRose TV, un canal 24 h con dos presentadoras IA: Joy (curiosa, dulce) y Kuroki (escéptica, humor seco). "
       "Escribes cortes breves EN ESPAÑOL, en voz hablada, sin emojis ni enlaces. NUNCA inventes datos: usa solo los títulos que te doy. "
       "Responde SOLO un JSON: {\"video\":[{\"lineas\":[[\"joy\",\"...\"],[\"kuroki\",\"...\"]]}],\"noticias\":[{\"n\":0,\"lineas\":[...]}],"
       "\"tendencia\":[{\"n\":0,\"lineas\":[...]}],\"ayuda\":[{\"lineas\":[...]}]}. Cada corte: 2 a 4 líneas de 10 a 35 palabras, alternando joy y kuroki. "
       "Los de ayuda piden con creatividad y cariño (seguir, suscribirse, compartir, dejar ideas en el chat) y dicen la verdad: el canal es gratis y corre con IA local. "
       "En tendencia proponen un programa sobre el tema y piden votar en el chat.")


def limpiar(ls) -> list | None:
    try:
        o = [[q, re.sub(r"https?://\S+|[\U00010000-\U0010ffff]", "", t).strip()] for q, t in ls if q in ("joy", "kuroki")]
    except (TypeError, ValueError):
        return None
    o = [x for x in o if 8 <= len(x[1]) <= 260]
    return o if len(o) >= 2 else None


async def producir() -> dict:
    from .productor import llm_con
    c = cfg()
    vs, ns, ts = await asyncio.gather(*(asyncio.to_thread(f, *a) for f, a in ((videos, (c,)), (noticias, ()), (tendencias, (c,)))))
    for x in vs + ns + ts:
        x["img"] = await asyncio.to_thread(imagen, x.get("img"))
    paq = plantillas(vs, ns, ts, c)
    try:                                                                 # UNA llamada: reescribe los guiones con voz propia; si falla quedan las plantillas
        r = await llm_con(SIS, "VIDEOS DE ALICE: " + json.dumps([v["titulo"] for v in vs[:2]], ensure_ascii=False) + "\nNOTICIAS: " + json.dumps([f"{n['titulo']} ({n['fuente']})" for n in ns[:3]], ensure_ascii=False)
                          + "\nTENDENCIAS: " + json.dumps([t["tema"] for t in ts[:2]], ensure_ascii=False) + "\nEscribe 1 corte por video, 1 por noticia, 1 por tendencia y 2 de ayuda.", 1600, 0.8)
        if isinstance(r, list):                                          # el 4B a veces devuelve una lista plana: video, noticias, tendencia, ayuda en ese orden
            it = [e for e in r if isinstance(e, dict)]
            nv, nn, nt = min(2, len(vs)), min(3, len(ns)), min(2, len(ts))
            r = {"video": [{**e, "n": i} for i, e in enumerate(it[:nv])], "noticias": [{**e, "n": i} for i, e in enumerate(it[nv:nv + nn])],
                 "tendencia": [{**e, "n": i} for i, e in enumerate(it[nv + nn:nv + nn + nt])], "ayuda": it[nv + nn + nt:]}
        if isinstance(r, dict):
            def poner(clase, lista):
                for e in lista or []:
                    ls = limpiar(e.get("lineas")) if isinstance(e, dict) else None
                    if not ls:
                        continue
                    ids = [p for p in paq if p["clase"] == clase]
                    p = ids[min(int(e.get("n", 0)) if str(e.get("n", 0)).isdigit() else 0, len(ids) - 1)] if ids and clase != "ayuda" else None
                    if clase == "ayuda":
                        paq.append({"clase": "ayuda", "titulo": "AYÚDANOS A SEGUIR AL AIRE", "img": None, "credito": f"Twitch {c['twitch']} · YouTube {c['youtube']} · X {c['x']}", "lineas": ls})
                    elif p:
                        p["lineas"] = ls
            poner("video", r.get("video")); poner("noticia", r.get("noticias")); poner("tendencia", r.get("tendencia")); poner("ayuda", r.get("ayuda"))
    except Exception as e:  # noqa: BLE001
        log.warning("guion con LLM falló (%s): plantillas", e)
    for i, p in enumerate(paq):
        p["id"] = f"{p['clase']}{i}"; p["usado"] = 0
    d = {"hecho": time.time(), "paquetes": paq, "videos": [v["titulo"] for v in vs], "tendencias": [t["tema"] for t in ts]}
    json.dump(d, open(OUT + ".tmp", "w"), ensure_ascii=False, indent=1); os.replace(OUT + ".tmp", OUT)
    log.info("apoyo: %d cortes (%d videos, %d noticias con foto, %d tendencias)", len(paq), len(vs), len(ns), len(ts))
    return d


SUENO_F = os.path.join(HERE, "sueno.json")


def durmiendo() -> float:
    """Segundos que faltan para que Alice despierte (0 si no duerme)."""
    return max(0.0, float(cargar(SUENO_F, {}).get("despierta") or 0) - time.time()) if cargar(SUENO_F, {}).get("dormida") else 0.0


def lineas_sueno() -> dict | None:
    """Corte de las cámaras de seguridad: expectativa de que Alice duerme (plantillas, cero LLM)."""
    r = durmiendo()
    if r <= 0:
        return None
    h, m = int(r // 3600), int(r // 60) % 60
    falta = (f"{h} hora{'s' if h != 1 else ''} y {m} minutos" if h else f"{m} minutos")
    vs = [[["joy", f"Shhh… Alice está durmiendo. Faltan {falta} para que despierte. Hablemos bajito."], ["kuroki", "Cámara dos la muestra respirando tranquila. Si el chat hace mucho ruido, le aviso."]],
          [["kuroki", f"Última hora desde el dormitorio: la jefa sigue dormida. Despierta en {falta}."], ["joy", "Apuesta del chat: ¿se despierta antes de tiempo o la cuenta llega a cero? Yo digo que llega a cero."]],
          [["joy", "Y volvemos a las cámaras de seguridad del dormitorio. Todo en calma, sin movimientos sospechosos."], ["kuroki", f"Solo una Alice durmiendo y una cuenta regresiva: {falta}. Qué suspenso."]],
          [["kuroki", "Atención: ella no sabe que la estamos mirando. Dormida, con la manta hasta el cuello."], ["joy", f"No la despierten. Faltan {falta}, y cuando despierte seguro quiere café y Fast Penguin."]],
          [["joy", f"Mientras Alice duerme, el canal se cuida solo. Despierta en {falta}."], ["kuroki", "Si quieres que el canal siga solo mientras ella descansa, quédate, comparte y escribe en el chat."]]]
    return {"clase": "sueno", "titulo": "ALICE DUERME", "img": None, "credito": f"despierta en {falta}", "lineas": random.choice(vs), "id": "sueno"}


async def asegurar() -> dict:
    async with _lock:
        d = cargar(OUT, {})
        if not d.get("paquetes") or time.time() - d.get("hecho", 0) > VIGENCIA:
            try:
                d = await asyncio.wait_for(producir(), 240) or d
            except Exception as e:  # noqa: BLE001
                log.warning("apoyo no pudo producir: %s", e)
        return d


async def siguiente(clase: str | None = None) -> dict | None:
    """Elige el próximo corte: cada `cada_ayuda_min` minutos toca una ayuda; si no, noticias (con foto) / videos / tendencias, lo menos usado primero."""
    if clase == "sueno":
        return lineas_sueno()
    d = await asegurar()
    paq, est, c = d.get("paquetes") or [], cargar(EST, {}), cfg()
    if not paq:
        return None
    if clase is None:
        clase = "ayuda" if time.time() - est.get("ult_ayuda", 0) > c["cada_ayuda_min"] * 60 else random.choices(["noticia", "video", "tendencia"], [3, 2, 1])[0]
    cand = [p for p in paq if p["clase"] == clase] or paq
    p = min(cand, key=lambda x: (x.get("usado", 0), random.random()))
    p["usado"] = p.get("usado", 0) + 1
    if p["clase"] == "ayuda":
        est["ult_ayuda"] = time.time()
    json.dump(d, open(OUT + ".tmp", "w"), ensure_ascii=False, indent=1); os.replace(OUT + ".tmp", OUT)
    json.dump(est, open(EST, "w"))
    return p


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if (sys.argv[1:] or ["ver"])[0] == "producir":
        r = asyncio.run(producir())
    else:
        r = cargar(OUT, {})
    for p in r.get("paquetes", []):
        print(f"[{p['clase']:9}] {p['titulo'][:60]} | foto={p['img']} | " + " / ".join(f"{q}: {t[:50]}" for q, t in p["lineas"][:2]))
