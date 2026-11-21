"""Conexión con la IA local: chequeos de salud que no cargan nada y la síntesis de prueba con XTTS.

Reglas:
  · «Probar conexión» nunca genera ni despierta modelos. El proxy del orquestador levanta XTTS con *cualquier*
    pedido HTTP, así que para la voz solo se abre el socket (y, si la persona configuró ia.voz.url_salud, se
    consulta ese /health directo, que no despierta nada).
  · La única instrucción fija es la técnica del formato de salida; todo lo creativo sale de la pantalla Estación.

API (la registra servidor.py):
  GET  /api/ia/instruccion            {"texto": INSTRUCCION_FORMATO}
  POST /api/ia/probar                 {"que": "llm"|"voz"} → {"ok", "estado", "detalle"}
  POST /api/reparto/{id}/probar_voz   {"frase": "..."} → audio/wav | {"error", "codigo"}
"""
from __future__ import annotations

import asyncio
import io
import re
import shutil
import time
import wave
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from aiohttp import web

from .proyecto import ErrorProyecto, mezclar, validar_perfil

INSTRUCCION_FORMATO = (
    "Responde SOLO con un objeto JSON válido, sin texto antes ni después y sin bloques de código:\n"
    '{"lineas": [{"quien": "<id del reparto>", "texto": "<lo que dice, en una o dos frases>", '
    '"expresion": "neutral|happy|sad|angry|surprised|relaxed", "gc": "<rótulo opcional o vacío>"}]}\n'
    "· «quien» debe ser uno de los id del reparto que se te indican.\n"
    "· Sin acotaciones, emojis ni nombres dentro de «texto»: solo lo que se dice en voz alta."
)

MAX_FRASE = 300
_NO_LETRA = re.compile(r"[^\w\s'¿?¡!]|_")


def solo_letras(texto: str) -> str:
    """XTTS lee puntos y símbolos como artefactos: quedan letras, números, apóstrofo y signos de pregunta/exclamación."""
    return " ".join(_NO_LETRA.sub(" ", texto).split())


def _base(url: str) -> str:
    """http://h:p/v1/chat/completions → http://h:p/v1"""
    p = urlsplit(url)
    camino = p.path
    for fin in ("/chat/completions", "/completions"):
        if camino.endswith(fin):
            camino = camino[: -len(fin)]
    return urlunsplit((p.scheme, p.netloc, camino.rstrip("/"), "", ""))


async def socket_abierto(url: str, espera: float = 1.5) -> bool:
    p = urlsplit(url)
    puerto = p.port or (443 if p.scheme == "https" else 80)
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(p.hostname, puerto), espera)
    except (OSError, asyncio.TimeoutError):
        return False
    w.close()
    try:
        await w.wait_closed()
    except OSError:
        pass
    return True


async def probar_llm(ia: dict) -> dict:
    url = ia["local"]["llm_url"]
    if ia["modo"] == "manual":
        return {"ok": True, "estado": "manual", "detalle": ""}
    if ia["modo"] == "online":
        return {"ok": False, "estado": "online_pendiente", "detalle": ""}
    t0 = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as s:
            async with s.get(_base(url) + "/models") as r:            # solo lista modelos: no genera nada
                ms = round((time.monotonic() - t0) * 1000)
                if r.status == 200:
                    try:
                        d = await r.json(content_type=None)
                        ids = [m.get("id", "") for m in d.get("data", []) if isinstance(m, dict)][:8]
                    except (ValueError, AttributeError):
                        ids = []
                    return {"ok": True, "estado": "listo", "detalle": ", ".join(i for i in ids if i), "ms": ms}
                # Responde pero sin /models (algunos servidores): está vivo.
                return {"ok": True, "estado": "responde", "detalle": f"HTTP {r.status}", "ms": ms}
    except asyncio.TimeoutError:
        return {"ok": False, "estado": "lento", "detalle": url}
    except aiohttp.ClientError:
        return {"ok": False, "estado": "no_responde", "detalle": url}


async def probar_voz(ia: dict) -> dict:
    vz = ia["voz"]
    if vz["url_salud"]:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as s:
                async with s.get(vz["url_salud"]) as r:
                    if r.status == 200:
                        return {"ok": True, "estado": "listo", "detalle": ""}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
    if await socket_abierto(vz["url"]):
        # El proxy está; XTTS puede estar dormido y se levanta al primer pedido de voz (~30 s).
        return {"ok": True, "estado": "dormido" if vz["url_salud"] else "proxy", "detalle": ""}
    return {"ok": False, "estado": "no_responde", "detalle": vz["url"]}


def _cambiar_tono(wav: bytes, factor: float) -> bytes:
    """Sube/baja el tono sin cambiar la velocidad (ffmpeg + rubberband). Si no hay ffmpeg, devuelve el original."""
    import subprocess
    if abs(factor - 1.0) < 1e-3 or not shutil.which("ffmpeg"):
        return wav
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-af",
                        f"rubberband=pitch={factor:.4f}:formant=preserved", "-f", "wav", "pipe:1"],
                       input=wav, capture_output=True, timeout=60)
    return r.stdout if r.returncode == 0 and r.stdout[:4] == b"RIFF" else wav


def _es_wav(b: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(b)) as w:
            return w.getnframes() > 0
    except (wave.Error, EOFError):
        return False


class ErrorVoz(Exception):
    def __init__(self, codigo: str, detalle: str = ""):
        super().__init__(detalle or codigo)
        self.codigo, self.detalle = codigo, detalle


async def sintetizar(ia: dict, perfil: dict, idioma_canal: str, frase: str, espera: float = 180) -> bytes:
    texto = solo_letras(frase)[:MAX_FRASE]
    if not texto:
        raise ErrorVoz("sin_frase")
    v = perfil["voz"]
    cuerpo = {"text": texto, "language": perfil["idioma"] or idioma_canal or "es",
              "temperature": v["temperatura"], "speed": v["velocidad"]}
    if v["voice"]:
        cuerpo["voice"] = v["voice"]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=espera, connect=5)) as s:
            async with s.post(ia["voz"]["url"], json=cuerpo) as r:
                datos = await r.read()
                if r.status == 503:
                    raise ErrorVoz("ocupado", datos.decode("utf-8", "replace")[:300])
                if r.status != 200:
                    raise ErrorVoz("rechazo", f"HTTP {r.status}: {datos.decode('utf-8', 'replace')[:300]}")
    except asyncio.TimeoutError:
        raise ErrorVoz("lento") from None
    except aiohttp.ClientConnectionError:
        raise ErrorVoz("no_responde", ia["voz"]["url"]) from None
    if not _es_wav(datos):
        raise ErrorVoz("rechazo", "la respuesta no es un WAV")
    return await asyncio.to_thread(_cambiar_tono, datos, v["tono"])


class IA:
    def __init__(self, proyecto, reparto):
        self.proyecto, self.reparto = proyecto, reparto
        self._voz = asyncio.Lock()               # una síntesis a la vez: la GPU tiene poca memoria

    async def get_instruccion(self, _req):
        return web.json_response({"texto": INSTRUCCION_FORMATO})

    async def post_probar(self, req):
        try:
            que = (await req.json()).get("que")
        except (ValueError, AttributeError):
            que = None
        ia = self.proyecto.datos["ia"]
        if que == "llm":
            return web.json_response(await probar_llm(ia))
        if que == "voz":
            return web.json_response(await probar_voz(ia))
        return web.json_response({"error": "que: llm | voz"}, status=400)

    async def post_probar_voz(self, req):
        rid = req.match_info["id"]
        if not self.reparto.existe(rid):
            raise web.HTTPNotFound(text="no existe")
        try:
            d = await req.json()
            frase = str(d.get("frase", ""))
            perfil = self.proyecto.perfil(rid)
            if isinstance(d.get("voz"), dict):          # probar los sliders sin guardarlos todavía
                perfil = validar_perfil(mezclar(perfil, {"voz": d["voz"]}))
        except (ValueError, AttributeError, ErrorProyecto) as e:
            return web.json_response({"error": str(e), "codigo": "pedido"}, status=400)
        if len(frase) > MAX_FRASE:
            return web.json_response({"error": f"máximo {MAX_FRASE} caracteres", "codigo": "larga"}, status=400)
        if self._voz.locked():
            return web.json_response({"error": "ya hay una prueba sonando", "codigo": "en_curso"}, status=409)
        async with self._voz:
            try:
                wav = await sintetizar(self.proyecto.datos["ia"], perfil, self.proyecto.datos["canal"]["idioma"], frase)
            except ErrorVoz as e:
                st = {"sin_frase": 400, "ocupado": 503, "lento": 504, "no_responde": 502}.get(e.codigo, 502)
                return web.json_response({"error": e.detalle, "codigo": e.codigo}, status=st)
        return web.Response(body=wav, content_type="audio/wav", headers={"Cache-Control": "no-store"})

    def registrar(self, r: web.UrlDispatcher) -> None:
        r.add_get("/api/ia/instruccion", self.get_instruccion)
        r.add_post("/api/ia/probar", self.post_probar)
        r.add_post("/api/reparto/{id}/probar_voz", self.post_probar_voz)
