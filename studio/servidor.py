"""Blackrose TV Studio — servidor local (aiohttp).

  python -m studio.servidor [--puerto 8840] [--proyecto DIR]

  /estudio            editor con vista previa (misma escena que la salida)
  /salida             lienzo 1920×1080 para la fuente Navegador de OBS (?plano= ?calidad= ?alpha=1)
  GET  /api/escena    escena actual (JSON)
  POST /api/escena    mezcla parcial (claves de primer nivel; «luces» y «colores» se mezclan por dentro) → difunde por /ws
  POST /api/plano     {"plano": "frontal|dos|grua|prensa|auto"} → difunde
  POST /api/habla     {"id": "<reparto>", "on": true|false} → difunde
  GET  /api/sets      sets disponibles
  /ws                 WebSocket: el servidor manda {"t": "escena"|"plano"|"habla", ...}
  /reparto/<archivo>  VRM y miniaturas del proyecto (solo lectura)

Escucha solo en 127.0.0.1. El proyecto vive fuera del repo por defecto: $BRTV_STUDIO_DATA o ~/BlackroseStudio/<canal>.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import re
import tempfile

from aiohttp import WSMsgType, web

log = logging.getLogger("studio")
AQUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(AQUI)
WEB = os.path.join(AQUI, "web")
VENDOR = os.path.join(REPO, "ligero", "web", "vendor")
SETS_DIR = os.path.join(WEB, "js", "sets")
PROYECTO_DEF = os.environ.get("BRTV_STUDIO_DATA") or os.path.expanduser("~/BlackroseStudio/mi-canal")

ESCENA_DEF: dict = {
    "set": "noticias",
    "ambiente": "noche",                      # noche | dia
    "plano": "auto",
    "canal": "",
    "titular": "",
    "colores": {"primario": "#ff2fd6", "secundario": "#00e5ff"},
    "luces": {"key": 1.0, "fill": 1.0, "rim": 1.0, "rim_color": ""},
    "reparto": [
        {"id": "p1", "nombre": "", "vrm": None, "pos": "mesa_izq", "color": "#ff6fb5"},
        {"id": "p2", "nombre": "", "vrm": None, "pos": "mesa_der", "color": "#7fe9ff"},
    ],
}
MEZCLA_INTERNA = ("luces", "colores")
_ID = re.compile(r"^[a-z0-9_]{1,32}$")
CLAVE_STUDIO: web.AppKey["Studio"] = web.AppKey("studio")


def sets_disponibles() -> list[str]:
    return sorted(f[:-3] for f in os.listdir(SETS_DIR) if f.endswith(".js") and _ID.match(f[:-3]))


def validar_parche(p: dict) -> dict:
    """Solo claves conocidas, con tipos razonables: la escena la leen páginas que no deben romperse."""
    if not isinstance(p, dict):
        raise ValueError("se esperaba un objeto JSON")
    fuera = set(p) - set(ESCENA_DEF)
    if fuera:
        raise ValueError(f"claves desconocidas: {sorted(fuera)}")
    if "set" in p and p["set"] not in sets_disponibles():
        raise ValueError(f"set inexistente: {p['set']}")
    if "ambiente" in p and p["ambiente"] not in ("noche", "dia"):
        raise ValueError("ambiente: noche | dia")
    for k in ("canal", "titular", "plano"):
        if k in p and not isinstance(p[k], str):
            raise ValueError(f"{k} debe ser texto")
    for k in MEZCLA_INTERNA:
        if k in p and not isinstance(p[k], dict):
            raise ValueError(f"{k} debe ser un objeto")
    if "luces" in p:
        for k, v in p["luces"].items():
            if k != "rim_color" and not (isinstance(v, (int, float)) and 0 <= v <= 3):
                raise ValueError(f"luces.{k} entre 0 y 3")
    if "reparto" in p:
        if not isinstance(p["reparto"], list) or len(p["reparto"]) > 12:
            raise ValueError("reparto: lista de hasta 12")
        for r in p["reparto"]:
            if not isinstance(r, dict) or not _ID.match(str(r.get("id", ""))):
                raise ValueError("cada integrante necesita un id [a-z0-9_]")
            vrm = r.get("vrm")
            if vrm is not None and not (isinstance(vrm, str) and re.match(r"^/reparto/[\w.\-]+\.vrm$", vrm)):
                raise ValueError("vrm debe ser /reparto/<archivo>.vrm")
    return p


class Studio:
    def __init__(self, proyecto: str):
        self.proyecto = proyecto
        self.reparto_dir = os.path.join(proyecto, "reparto")
        os.makedirs(self.reparto_dir, exist_ok=True)
        self.archivo = os.path.join(proyecto, "escena.json")
        self.escena = copy.deepcopy(ESCENA_DEF)
        try:
            with open(self.archivo, encoding="utf-8") as f:
                guardada = json.load(f)
            self.escena.update(validar_parche({k: v for k, v in guardada.items() if k in ESCENA_DEF}))
        except (OSError, ValueError) as e:
            if not isinstance(e, FileNotFoundError):
                log.warning("escena guardada inválida (%s); uso la de fábrica", e)
        self.clientes: set[web.WebSocketResponse] = set()

    def guardar(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.proyecto, suffix=".tmp")       # escritura atómica: un corte no deja el JSON a medias
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.escena, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.archivo)

    async def difundir(self, msg: dict) -> None:
        txt = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.clientes):
            try:
                await ws.send_str(txt)
            except (ConnectionError, RuntimeError):
                self.clientes.discard(ws)

    def mezclar(self, p: dict) -> None:
        for k, v in p.items():
            if k in MEZCLA_INTERNA:
                self.escena[k] = {**self.escena.get(k, {}), **v}
            else:
                self.escena[k] = v

    # ── rutas ──
    async def get_escena(self, _req):
        return web.json_response(self.escena)

    async def post_escena(self, req):
        try:
            p = validar_parche(await req.json())
        except (ValueError, json.JSONDecodeError) as e:
            return web.json_response({"error": str(e)}, status=400)
        self.mezclar(p)
        self.guardar()
        await self.difundir({"t": "escena", "d": self.escena})
        return web.json_response(self.escena)

    async def post_plano(self, req):
        try:
            plano = str((await req.json()).get("plano", ""))
        except (ValueError, AttributeError):
            return web.json_response({"error": "JSON inválido"}, status=400)
        if not _ID.match(plano):
            return web.json_response({"error": "plano inválido"}, status=400)
        self.escena["plano"] = plano
        self.guardar()
        await self.difundir({"t": "plano", "plano": plano})
        return web.json_response({"plano": plano})

    async def post_habla(self, req):
        try:
            d = await req.json()
            rid, on = str(d.get("id", "")), bool(d.get("on"))
        except (ValueError, AttributeError):
            return web.json_response({"error": "JSON inválido"}, status=400)
        await self.difundir({"t": "habla", "id": rid, "on": on})
        return web.json_response({"id": rid, "on": on})

    async def get_sets(self, _req):
        return web.json_response(sets_disponibles())

    async def ws(self, req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        self.clientes.add(ws)
        await ws.send_str(json.dumps({"t": "escena", "d": self.escena}, ensure_ascii=False))
        try:
            async for m in ws:
                if m.type == WSMsgType.ERROR:
                    break
        finally:
            self.clientes.discard(ws)
        return ws


def pagina(nombre: str):
    ruta = os.path.join(WEB, nombre)

    async def h(_req):
        return web.FileResponse(ruta, headers={"Cache-Control": "no-cache"})
    return h


def crear_app(proyecto: str = PROYECTO_DEF) -> web.Application:
    st = Studio(proyecto)
    app = web.Application(client_max_size=256 * 1024)
    app[CLAVE_STUDIO] = st
    r = app.router
    async def raiz(_req):
        raise web.HTTPFound("/estudio")
    r.add_get("/", raiz)
    r.add_get("/estudio", pagina("index.html"))
    r.add_get("/salida", pagina("salida.html"))
    r.add_get("/api/escena", st.get_escena)
    r.add_post("/api/escena", st.post_escena)
    r.add_post("/api/plano", st.post_plano)
    r.add_post("/api/habla", st.post_habla)
    r.add_get("/api/sets", st.get_sets)
    r.add_get("/ws", st.ws)
    r.add_static("/js/", os.path.join(WEB, "js"), show_index=False)
    r.add_static("/css/", os.path.join(WEB, "css"), show_index=False)
    r.add_static("/i18n/", os.path.join(WEB, "i18n"), show_index=False)
    r.add_static("/vendor/", VENDOR, show_index=False)
    r.add_static("/reparto/", st.reparto_dir, show_index=False)
    return app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("BRTV_STUDIO_PUERTO", 8840)))
    ap.add_argument("--proyecto", default=PROYECTO_DEF)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    log.info("Studio en http://127.0.0.1:%d/estudio · proyecto %s", a.puerto, a.proyecto)
    web.run_app(crear_app(a.proyecto), host="127.0.0.1", port=a.puerto, print=None)


if __name__ == "__main__":
    main()
