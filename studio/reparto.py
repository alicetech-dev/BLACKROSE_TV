"""Mi Reparto: los VRM importados del proyecto.

  <proyecto>/reparto/<id>.vrm         el modelo que usa el estudio (optimizado si hacía falta)
  <proyecto>/reparto/<id>.json        ficha: nombre, archivo original, fecha, informe de validación
  <proyecto>/reparto/<id>.png         miniatura (la que trae el VRM o la que renderiza el navegador)
  <proyecto>/reparto/originales/<id>.vrm   el archivo tal como llegó, si se optimizó

API (la registra servidor.py):
  GET    /api/reparto                  lista
  POST   /api/reparto                  multipart: «vrm» (archivo), «optimizar» (1|0, por defecto 1) → 201 ficha | 422 errores
  POST   /api/reparto/{id}/miniatura   cuerpo image/png (≤ 2 MB)
  DELETE /api/reparto/{id}
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import tempfile
import unicodedata

from aiohttp import web

from . import vrm as V

_ID = re.compile(r"^[a-z0-9_]{1,32}$")
MAX_MINI = 2 * 1024 * 1024
PNG = b"\x89PNG\r\n\x1a\n"


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:28]
    return t or "avatar"


def _escribir(ruta: str, datos: bytes) -> None:
    d = os.path.dirname(ruta)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(datos)
    os.replace(tmp, ruta)


class Reparto:
    def __init__(self, carpeta: str, al_borrar=None):
        self.dir = carpeta
        self.orig = os.path.join(carpeta, "originales")
        os.makedirs(self.orig, exist_ok=True)
        self.al_borrar = al_borrar                    # callback async(id) para limpiar la escena

    def ruta(self, rid: str, ext: str) -> str:
        if not _ID.match(rid):
            raise web.HTTPBadRequest(text="id inválido")
        return os.path.join(self.dir, f"{rid}.{ext}")

    def existe(self, rid: str) -> bool:
        return bool(_ID.match(rid)) and os.path.isfile(os.path.join(self.dir, f"{rid}.vrm"))

    def ficha(self, rid: str) -> dict | None:
        try:
            with open(self.ruta(rid, "json"), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return None
        d["id"] = rid
        d["vrm"] = f"/reparto/{rid}.vrm"
        d["miniatura"] = f"/reparto/{rid}.png" if os.path.isfile(self.ruta(rid, "png")) else None
        return d

    def lista(self) -> list[dict]:
        ids = sorted(f[:-4] for f in os.listdir(self.dir) if f.endswith(".vrm") and _ID.match(f[:-4]))
        return [f for f in (self.ficha(i) for i in ids) if f]

    def id_libre(self, base: str) -> str:
        rid, n = base, 2
        while os.path.exists(os.path.join(self.dir, f"{rid}.vrm")):
            rid = f"{base[:28]}_{n}"
            n += 1
        return rid

    # ── rutas ──
    async def get_lista(self, _req):
        return web.json_response(self.lista())

    async def post_importar(self, req: web.Request):
        if not req.content_type.startswith("multipart/"):
            return web.json_response({"errores": ["se espera un formulario con el archivo .vrm"]}, status=400)
        datos, nombre_arch, optimizar = None, "", True
        lector = await req.multipart()
        async for parte in lector:
            if parte.name == "vrm":
                nombre_arch = parte.filename or ""
                buf, total = bytearray(), 0
                while trozo := await parte.read_chunk(1 << 20):
                    total += len(trozo)
                    if total > V.MAX_ARCHIVO:
                        return web.json_response({"errores": [f"el archivo supera {V.MAX_ARCHIVO // 2**20} MB"]}, status=413)
                    buf += trozo
                datos = bytes(buf)
            elif parte.name == "optimizar":
                optimizar = (await parte.text()).strip() not in ("0", "false", "no")
        if not datos:
            return web.json_response({"errores": ["no llegó ningún archivo"]}, status=400)
        if not nombre_arch.lower().endswith((".vrm", ".glb")):
            return web.json_response({"errores": ["el archivo debe ser .vrm"]}, status=400)
        try:
            informe = await asyncio.to_thread(V.analizar, datos)
        except V.VRMError as e:
            return web.json_response({"errores": [str(e)]}, status=422)
        if not informe["ok"]:
            return web.json_response({"errores": informe["errores"], "avisos": informe["avisos"]}, status=422)

        rid = self.id_libre(slug(informe["nombre"] or os.path.splitext(os.path.basename(nombre_arch))[0]))
        usado, achicadas = datos, 0
        if optimizar and informe["stats"]["texturas_grandes"]:
            usado, achicadas = await asyncio.to_thread(V.optimizar, datos)
            if achicadas:
                await asyncio.to_thread(_escribir, os.path.join(self.orig, f"{rid}.vrm"), datos)
                informe["avisos"] = [a for a in informe["avisos"] if f"{V.LADO_MAX} px" not in a]
                informe["avisos"].insert(0, f"{achicadas} textura(s) achicadas a {V.LADO_MAX} px (el original quedó guardado)")
        mini = await asyncio.to_thread(V.miniatura, datos, informe)
        await asyncio.to_thread(_escribir, self.ruta(rid, "vrm"), usado)
        if mini:
            await asyncio.to_thread(_escribir, self.ruta(rid, "png"), mini)
        informe.pop("texturas", None)
        ficha = {
            "nombre": informe["nombre"] or rid, "archivo": os.path.basename(nombre_arch), "importado": dt.datetime.now().isoformat(timespec="seconds"),
            "optimizado": {"texturas": achicadas, "bytes_antes": len(datos), "bytes_ahora": len(usado)} if achicadas else None,
            "informe": informe,
        }
        _escribir(self.ruta(rid, "json"), json.dumps(ficha, ensure_ascii=False, indent=1).encode())
        return web.json_response(self.ficha(rid), status=201)

    async def post_miniatura(self, req: web.Request):
        rid = req.match_info["id"]
        if not self.existe(rid):
            raise web.HTTPNotFound(text="no existe")
        buf = bytearray()                                  # read(n) devuelve lo que haya llegado, no todo: leer hasta EOF
        while trozo := await req.content.read(1 << 16):
            buf += trozo
            if len(buf) > MAX_MINI:
                break
        datos = bytes(buf)
        if len(datos) > MAX_MINI or not datos.startswith(PNG):
            return web.json_response({"error": "se espera un PNG de hasta 2 MB"}, status=400)
        _escribir(self.ruta(rid, "png"), datos)
        return web.json_response(self.ficha(rid))

    async def delete(self, req: web.Request):
        rid = req.match_info["id"]
        if not self.existe(rid):
            raise web.HTTPNotFound(text="no existe")
        for ext in ("vrm", "json", "png"):
            try:
                os.remove(self.ruta(rid, ext))
            except FileNotFoundError:
                pass
        try:
            os.remove(os.path.join(self.orig, f"{rid}.vrm"))
        except FileNotFoundError:
            pass
        if self.al_borrar:
            await self.al_borrar(rid)
        return web.json_response({"borrado": rid})

    def registrar(self, r: web.UrlDispatcher) -> None:
        r.add_get("/api/reparto", self.get_lista)
        r.add_post("/api/reparto", self.post_importar)
        r.add_post("/api/reparto/{id}/miniatura", self.post_miniatura)
        r.add_delete("/api/reparto/{id}", self.delete)
