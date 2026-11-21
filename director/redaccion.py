"""Redacción de BlackRose TV: noticias que trae Blackrose (3-4 capturas + recorte + artículo pegado o link).

Cada nota vive en logs/redaccion/<id>/ (imágenes + nota.json). Al subirla, Grok (visión) lee capturas, recorte y texto
y arma una FICHA (título, medio, resumen, datos concretos, ángulo para debatir): con eso las dolls la cuentan sin
inventar. La programación (programacion.py) toma la siguiente nota «lista» en el próximo hueco de noticias: la del
bloque que se eligió, o en cualquier bloque si es «auto». Estados: procesando → lista → al_aire → emitida (o error).
Lo usan el servidor del overlay (blackrose_tv_srv.py: página /redaccion y /api/redaccion) y el director (programacion).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

import aiohttp

log = logging.getLogger("director.redaccion")
RAIZ = Path(__file__).resolve().parent.parent / "logs" / "redaccion"
CEREBRO = os.environ.get("CEREBRO_URL", "http://127.0.0.1:8087/v1/chat/completions")   # 100 % local, sin Grok
MAX_IMG = 5

FICHA = """Eres la editora de BlackRose TV. Blackrose (la dueña del canal) trajo esta noticia a la redacción: capturas de
pantalla, el recorte de la noticia y/o el texto del artículo. Léelo TODO con cuidado (el texto de las imágenes también)
y arma la ficha para que las conductoras la cuenten en vivo, en español neutro. No inventes nada que no esté en el
material: si un dato no aparece, no lo pongas. Responde SOLO este JSON:
{"titulo": "titular corto y claro (máx. 110 caracteres)",
 "fuente": "medio o sitio de origen si se ve (si no, \\"Redacción BlackRose\\")",
 "fecha": "fecha del hecho si aparece, si no \\"\\"",
 "resumen": "4 a 6 frases: qué pasó, quién, cuándo, por qué importa",
 "datos": ["3 a 6 datos concretos textuales: cifras, nombres, citas, fechas"],
 "contexto": "1-2 frases de contexto general (marcado como contexto)",
 "angulo": "una pregunta o tensión interesante para debatir en vivo",
 "bloque": "tecnologia | gamer | ia | internacional (el que mejor le calce)"}"""


def _clave() -> str:
    k = os.getenv("GROK_API_KEY", "")
    if not k:
        try:
            for ln in open(os.path.expanduser("~/.env"), encoding="utf-8"):
                if ln.startswith("GROK_API_KEY="):
                    k = ln.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
    return k


def _guardar(n: dict) -> None:
    d = RAIZ / n["id"]
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "nota.json.tmp"
    tmp.write_text(json.dumps(n, ensure_ascii=False, indent=1))
    tmp.replace(d / "nota.json")  # atómico: el director lee mientras el overlay escribe


def leer(id_: str) -> dict | None:
    try:
        return json.loads((RAIZ / id_ / "nota.json").read_text())
    except (OSError, ValueError):
        return None


def listar() -> list[dict]:
    if not RAIZ.exists():
        return []
    notas = [n for d in RAIZ.iterdir() if d.is_dir() and (n := leer(d.name))]
    return sorted(notas, key=lambda n: (n.get("orden", n["creada"])))


def marcar(id_: str, estado: str, **extra) -> None:
    n = leer(id_)
    if n:
        n.update(estado=estado, **extra)
        _guardar(n)


def borrar(id_: str) -> bool:
    d = RAIZ / re.sub(r"[^\w-]", "", id_)
    if not d.is_dir():
        return False
    for f in d.iterdir():
        f.unlink()
    d.rmdir()
    return True


def siguiente(bloque_id: str) -> dict | None:
    """La próxima nota lista para este bloque (o «auto»); la más vieja primero."""
    for n in listar():
        if n.get("estado") == "lista" and n.get("bloque", "auto") in ("auto", bloque_id):
            return n
    return None


def _a_jpeg(datos: bytes, lado: int = 1600) -> bytes:
    """Achica capturas grandes (Grok y el overlay no necesitan 4K) y las deja en JPEG."""
    from PIL import Image
    im = Image.open(io.BytesIO(datos))
    im = im.convert("RGB")
    im.thumbnail((lado, lado))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88)
    return out.getvalue()


def crear(imagenes: list[bytes], recorte: bytes | None, texto: str, titulo: str, fuente: str, bloque: str) -> dict:
    id_ = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    d = RAIZ / id_
    d.mkdir(parents=True, exist_ok=True)
    nombres = []
    for i, b in enumerate(([recorte] if recorte else []) + imagenes[:MAX_IMG]):
        nom = ("recorte" if (recorte and i == 0) else f"captura{i}") + ".jpg"
        (d / nom).write_bytes(_a_jpeg(b))
        nombres.append(nom)
    n = {"id": id_, "creada": time.time(), "estado": "procesando", "bloque": bloque or "auto", "texto": texto[:20000],
         "titulo_manual": titulo[:160], "fuente_manual": fuente[:80], "imagenes": nombres, "ficha": None, "error": ""}
    _guardar(n)
    return n


async def _bajar_articulo(url: str) -> str:
    """Si pegó un link: baja la página y deja el texto de los párrafos (sin JS; alcanza para la mayoría de los medios)."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        async with s.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
            html = await r.text(errors="ignore")
    html = re.sub(r"(?is)<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>", " ", html)
    tit = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    pars = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p)).strip() for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", html)]
    cuerpo = "\n".join(p for p in pars if len(p) > 60)
    return (f"TÍTULO DE LA PÁGINA: {tit.group(1).strip()}\n" if tit else "") + f"URL: {url}\n" + cuerpo[:15000]


async def procesar(id_: str) -> dict | None:
    n = leer(id_)
    if not n:
        return None
    try:
        texto = n.get("texto", "").strip()
        if re.fullmatch(r"https?://\S+", texto):
            texto = await _bajar_articulo(texto)
        # Sin APIs de pago no hay visión: el texto de las capturas sale por OCR local (tesseract), si está instalado.
        ocr = []
        for nom in n["imagenes"]:
            try:
                p = await asyncio.create_subprocess_exec("tesseract", str(RAIZ / id_ / nom), "-", "-l", "spa+eng",
                                                         stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                o, _ = await asyncio.wait_for(p.communicate(), 60)
                if o.strip():
                    ocr.append(o.decode("utf-8", "ignore").strip())
            except (OSError, asyncio.TimeoutError):
                pass
        extra = ""
        if n.get("titulo_manual"):
            extra += f"\nTítulo que puso Blackrose: {n['titulo_manual']}"
        if n.get("fuente_manual"):
            extra += f"\nMedio que indicó Blackrose: {n['fuente_manual']}"
        if ocr:
            extra += "\n\nTEXTO DE LAS CAPTURAS (OCR):\n" + "\n---\n".join(ocr)[:8000]
        if texto:
            extra += f"\n\nTEXTO DEL ARTÍCULO:\n{texto[:9000]}"
        if not ocr and not texto and not n.get("titulo_manual"):
            raise ValueError("sin texto: el modelo local no ve imágenes; pega el texto o el enlace de la noticia")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240)) as s:
            async with s.post(CEREBRO, json={"model": "profundo", "max_tokens": 900, "temperature": 0.2,
                                             "messages": [{"role": "system", "content": FICHA}, {"role": "user", "content": extra.strip()}]}) as r:
                d = await r.json(content_type=None)
        if "choices" not in d:
            raise RuntimeError(str(d)[:300])
        txt = d["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", txt, re.S)
        ficha = json.loads(m.group(0)) if m else None
        if not ficha or not ficha.get("titulo"):
            raise ValueError("el modelo local no devolvió la ficha: " + txt[:200])
        if n.get("titulo_manual"):
            ficha["titulo"] = n["titulo_manual"]
        if n.get("fuente_manual"):
            ficha["fuente"] = n["fuente_manual"]
        n = leer(id_) or n  # pudo cambiar el bloque mientras tanto
        if n.get("bloque", "auto") == "auto" and ficha.get("bloque") in ("tecnologia", "gamer", "ia", "internacional"):
            n["bloque_sugerido"] = ficha["bloque"]
        n.update(ficha=ficha, estado="lista", error="")
    except Exception as e:  # noqa: BLE001
        log.warning("redacción %s: %s", id_, e)
        n = leer(id_) or n
        n.update(estado="error", error=str(e)[:300])
    if not (RAIZ / id_).is_dir():  # la borraron mientras el modelo leía: no resucitarla
        return None
    _guardar(n)
    return n


def a_nota(n: dict) -> dict:
    """La nota de la redacción en el formato de programacion.py (titular + ficha + imágenes para el overlay)."""
    f = n.get("ficha") or {}
    return {"titulo": f.get("titulo") or n.get("titulo_manual") or "Noticia de la redacción",
            "fuente": f.get("fuente") or "Redacción BlackRose", "t": n.get("creada", time.time()), "relacionadas": [],
            "ficha": f, "propia": n["id"],
            "imagenes": [f"/redaccion/img/{n['id']}/{x}" for x in n.get("imagenes", [])]}


async def _probar():  # python -m director.redaccion <id>: reprocesa una nota
    import sys
    print(json.dumps(await procesar(sys.argv[1]), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(_probar())
