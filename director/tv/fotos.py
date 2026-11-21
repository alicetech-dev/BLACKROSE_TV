"""FOTOS de BlackRose TV (pedido 2026-11-20: «no solo texto, usa imágenes; recorta la imagen de la noticia o de los artículos»).

Nada generado: las imágenes son las REALES de cada nota o artículo, recortadas a 16:9 (1280×720) y con su crédito.
  · pool de noticias: feeds RSS directos (traen foto propia: media:content / enclosure / <img> / og:image de la página)
      → cada nota con su foto, enlace, fuente y un resumen (más datos verídicos para el guion que el titular de Google News)
  · para(texto): busca en el pool la nota que más se parece a un titular (de Google News u otro) y devuelve su foto
  · wiki(tema): fotos del artículo de Wikipedia en español del tema (Wikimedia Commons, licencias libres)
Todo cae con elegancia: sin red o sin foto → None y el programa sigue con texto.
  .venv/bin/python -m director.tv.fotos pool | wiki "Canal de Panamá" | para "titular"
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

log = logging.getLogger("fotos")
HERE = os.path.dirname(os.path.abspath(__file__))
MEDIOS = os.path.join(HERE, "medios")            # lo sirven :8830 y :8822 en /medios/
POOL_F = os.path.join(HERE, "fotos_pool.json")
WIKI_F = os.path.join(HERE, "fotos_wiki.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 BlackRoseTV"}
FEEDS = [  # (fuente, categoría, url)
    ("Xataka", "tech", "https://www.xataka.com/feedburner.xml"),
    ("Genbeta", "tech", "https://www.genbeta.com/feedburner.xml"),
    ("Hipertextual", "tech", "https://hipertextual.com/feed"),
    ("El País Tecnología", "tech", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/tecnologia/portada"),
    ("Xataka Ciencia", "ciencia", "https://www.xatakaciencia.com/feedburner.xml"),
    ("3DJuegos", "juegos", "https://www.3djuegos.com/feedburner.xml"),
    ("VidaExtra", "juegos", "https://www.vidaextra.com/feedburner.xml"),
    ("BBC Mundo", "mundo", "https://feeds.bbci.co.uk/mundo/rss.xml"),
    ("France 24", "mundo", "https://www.france24.com/es/rss"),
    ("El País Internacional", "mundo", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada"),
    ("Infobae América", "mundo", "https://www.infobae.com/arc/outboundfeeds/rss/category/america/"),
    ("Marca", "deportes", "https://e00-marca.uecdn.es/rss/portada.xml"),
]
NS = {"media": "http://search.yahoo.com/mrss/", "content": "http://purl.org/rss/1.0/modules/content/"}
STOP = set("para como este esta pero sobre entre desde hasta cuando donde porque tiene tienen hace será sido todo toda todos todas otro otra "
           "nuevo nueva nuevos nuevas años parte según tras ante bajo puede pueden mientras durante sobre aunque cómo qué quién".split())
VIGENCIA = 25 * 60
# temas que el canal NO toca (reglas de SISTEMA): elecciones, campañas, migración, tragedias, atentados, muertes, abusos
VETO = re.compile(r"elecci|electoral|campaña|candidat|votaci|sufrag|migra|refugiad|atentad|asesin|muert|fallec|víctima|tiroteo|masacre|violaci|abuso|suicid|"
                  r"genocid|terroris|secuestr|cadáver|herid|tragedia|accidente mortal|naufrag|guerra civil", re.I)


def _get(url: str, t: int = 12, tope: int = 4_000_000) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t) as r:
        return r.read(tope)


def _cargar(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return d


def _guardar(p, d) -> None:
    tmp = p + f".tmp{os.getpid()}"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, p)


def palabras(t: str) -> set[str]:
    return {w for w in re.findall(r"\w{4,}", (t or "").lower()) if w not in STOP and not w.isdigit()}


def texto_plano(h: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


# ───────────────────────────── recorte 16:9 ─────────────────────────────
def recortar(url: str, credito: str = "", ancho: int = 1280) -> dict | None:
    """Baja la foto (≤4 MB), la recorta a 16:9 (centro, un poco hacia arriba: las caras suelen estar arriba) y la guarda en medios/.
    Devuelve {"web": "/medios/x.jpg", "ruta": "/abs/x.jpg", "credito": ...} o None si no es una foto decente."""
    if not url or not url.startswith("http"):
        return None
    os.makedirs(MEDIOS, exist_ok=True)
    nom = hashlib.sha1(url.encode()).hexdigest()[:16] + "_169.jpg"
    ruta = os.path.join(MEDIOS, nom)
    if not os.path.exists(ruta):
        try:
            from PIL import Image
            b = _get(url, 15)
            im = Image.open(io.BytesIO(b))
            im = im.convert("RGB")
            w, h = im.size
            if w < 360 or h < 200:          # miniaturas e íconos: no
                return None
            if w / h > 16 / 9:              # muy ancha → se recorta a los lados (centro)
                nw = int(h * 16 / 9)
                im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
            else:                           # alta → se recorta arriba/abajo con sesgo al tercio superior
                nh = int(w * 9 / 16)
                y = int((h - nh) * 0.35)
                im = im.crop((0, y, w, y + nh))
            im = im.resize((ancho, ancho * 9 // 16), Image.LANCZOS)
            im.save(ruta + ".tmp.jpg", "JPEG", quality=86)
            os.replace(ruta + ".tmp.jpg", ruta)
        except Exception as e:  # noqa: BLE001
            log.info("foto %s: %s", url[:70], e)
            return None
    return {"web": "/medios/" + nom, "ruta": ruta, "credito": credito}


def og_image(link: str) -> str | None:
    try:
        h = _get(link, 10, 600_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)', h) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)', h)
    return html.unescape(m.group(1)) if m else None


# ───────────────────────────── pool de noticias con foto ─────────────────────────────
def _item_img(it) -> str | None:
    for tag in ("media:content", "media:thumbnail"):
        for e in it.findall(tag, NS):
            u = e.get("url")
            if u and (e.get("medium") in (None, "image") or re.search(r"\.(jpe?g|png|webp)", u, re.I)):
                return u
    e = it.find("enclosure")
    if e is not None and (e.get("type") or "image").startswith("image"):
        return e.get("url")
    for campo in ("content:encoded", "description"):
        m = re.search(r'<img[^>]+src=["\']([^"\']+)', it.findtext(campo, "", NS) or "")
        if m:
            return html.unescape(m.group(1))
    return None


def pool(forzar: bool = False) -> list[dict]:
    """Notas recientes de los feeds directos, cada una con su foto (url original; el recorte se hace al usarla). Caché 25 min."""
    c = _cargar(POOL_F, {})
    if not forzar and time.time() - c.get("t", 0) < VIGENCIA and c.get("items"):
        return c["items"]
    out = []
    for fuente, cat, url in FEEDS:
        try:
            raiz = ET.fromstring(_get(url, 12))
        except Exception as e:  # noqa: BLE001
            log.info("feed %s: %s", fuente, e)
            continue
        for it in list(raiz.iter("item"))[:25]:
            tit = texto_plano(it.findtext("title") or "")
            if len(tit) < 20:
                continue
            try:
                ts = parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
            except (TypeError, ValueError):
                ts = time.time()
            if time.time() - ts > 3 * 86400:
                continue
            res = texto_plano(it.findtext("description") or "")[:420]
            out.append({"titulo": tit, "fuente": fuente, "cat": cat, "link": (it.findtext("link") or "").strip(), "img": _item_img(it),
                        "resumen": res if res.lower()[:40] != tit.lower()[:40] else "", "ts": ts})
    if out:
        _guardar(POOL_F, {"t": time.time(), "items": out})
        return out
    return c.get("items", [])


def foto_de_nota(n: dict) -> dict | None:
    u = n.get("img") or (og_image(n["link"]) if n.get("link") else None)
    return recortar(u, f"Foto: {n['fuente']}") if u else None


def para(texto: str, cat: str | None = None, umbral: float = 0.34) -> tuple[dict | None, dict | None]:
    """(nota del pool más parecida, su foto recortada) para un titular cualquiera; (None, None) si nada se parece lo suficiente."""
    A = palabras(texto)
    if len(A) < 2:
        return None, None
    mejor, pun = None, 0.0
    for n in pool():
        if cat and n["cat"] != cat and cat != "*":
            continue
        B = palabras(n["titulo"] + " " + n.get("resumen", "")[:160])
        s = len(A & B) / max(1, min(len(A), 8))
        if s > pun:
            mejor, pun = n, s
    if not mejor or pun < umbral:
        return None, None
    return mejor, foto_de_nota(mejor)


def titulares_foto(cats: list[str], vistos: set[str], n: int = 5, claves: list[str] | None = None) -> list[dict]:
    """Titulares REALES con FOTO para el noticiero (formato compatible con show_kuroki.titulares + img/resumen/link).
    claves: palabras para preferir notas del rubro del programa."""
    ks = {k.lower() for c in (claves or []) for k in re.findall(r"\w{4,}", c)}
    cand = [x for x in pool() if x["cat"] in cats and re.sub(r"\W+", "", x["titulo"].lower())[:60] not in vistos
            and (x["cat"] == "mundo" or not VETO.search(x["titulo"] + " " + x.get("resumen", "")[:200]))]
    cand.sort(key=lambda x: (-len(palabras(x["titulo"] + " " + x.get("resumen", "")) & ks), -x["ts"]))
    out = []
    for x in cand:
        if len(out) >= n:
            break
        if any(len(palabras(x["titulo"]) & palabras(o["titulo"])) >= 3 for o in out):    # la misma historia contada por dos medios
            continue
        f = foto_de_nota(x)
        if not f:
            continue
        out.append({"titulo": x["titulo"], "fuente": x["fuente"], "horas": max(1, round((time.time() - x["ts"]) / 3600)),
                    "resumen": x.get("resumen", ""), "link": x.get("link", ""), "img": f})
    return out


# ───────────────────────────── Wikipedia (temas de divulgación) ─────────────────────────────
def wiki(tema: str, n: int = 4) -> list[dict]:
    """Hasta n fotos del artículo de Wikipedia en español que mejor calza con el tema (caché por tema)."""
    cache = _cargar(WIKI_F, {})
    k = tema.strip().lower()[:120]
    if k in cache and time.time() - cache[k].get("t", 0) < 7 * 86400:
        return [f for f in cache[k]["fotos"] if os.path.exists(f["ruta"])]
    fotos: list[dict] = []
    try:
        q = re.sub(r"^(tendencia de hoy:|la |el |los |las )", "", tema.strip(), flags=re.I)[:90]
        r = json.loads(_get("https://es.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": q, "srlimit": 1, "format": "json"}), 10))
        hits = r.get("query", {}).get("search", [])
        if hits:
            titulo = hits[0]["title"]
            ml = json.loads(_get("https://es.wikipedia.org/api/rest_v1/page/media-list/" + urllib.parse.quote(titulo.replace(" ", "_")), 10))
            for it in ml.get("items", []):
                if it.get("type") != "image":
                    continue
                src = None
                for s in (it.get("srcset") or [])[::-1]:
                    src = s.get("src")
                    break
                if not src or re.search(r"\.svg|icon|logo|flag|bandera|escudo|map[a_]|locator", src, re.I):
                    continue
                src = ("https:" + src) if src.startswith("//") else src
                f = recortar(src, f"Foto: Wikimedia Commons · «{titulo}»")
                if f:
                    fotos.append(f)
                if len(fotos) >= n:
                    break
    except Exception as e:  # noqa: BLE001
        log.info("wiki «%s»: %s", tema[:50], e)
    cache[k] = {"t": time.time(), "fotos": fotos}
    try:
        _guardar(WIKI_F, cache)
    except OSError:
        pass
    return fotos


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    a = sys.argv[1:] or ["pool"]
    if a[0] == "pool":
        p = pool(True)
        print(len(p), "notas;", sum(1 for x in p if x.get("img")), "con foto en el feed")
        for x in titulares_foto(["tech", "ciencia"], set(), 3):
            print(x["titulo"][:80], "|", x["fuente"], "|", x["img"]["web"])
    elif a[0] == "wiki":
        print(json.dumps(wiki(a[1]), ensure_ascii=False, indent=1))
    elif a[0] == "para":
        n, f = para(a[1], "*")
        print(n and n["titulo"], f)
