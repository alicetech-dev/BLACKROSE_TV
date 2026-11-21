"""Servicio propio del Show de Kuroki (:8824, brtv-show.service): API + página + orquestador, aparte del overlay :8822
para que reiniciar el overlay no corte el show.
  POST /api/showkuroki {"accion":"iniciar","tanda":true} | {"accion":"parar"} · GET = estado · página: /showkuroki/
"""
from __future__ import annotations

import argparse
import logging
import os

from aiohttp import web

from .show_kuroki import PUERTO, ShowKuroki

HERE = os.path.dirname(os.path.abspath(__file__))


def app() -> web.Application:
    sk = ShowKuroki()

    async def api(r: web.Request) -> web.Response:
        if r.method == "POST":
            try:
                d = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            if d.get("accion") == "iniciar":
                res = await sk.iniciar(tanda=bool(d.get("tanda", True)), obs=bool(d.get("obs", True)))
            elif d.get("accion") == "parar":
                res = await sk.parar()
            else:
                return web.json_response({"ok": False, "error": "accion: iniciar | parar"}, status=400)
            return web.json_response({**res, **sk.estado()})
        return web.json_response(sk.estado(), headers={"Cache-Control": "no-store"})

    a = web.Application()
    a.router.add_route("*", "/api/showkuroki", api)
    a.router.add_get("/showkuroki", lambda r: web.HTTPFound("/showkuroki/"))
    a.router.add_get("/showkuroki/", lambda r: web.FileResponse(os.path.join(HERE, "web", "showkuroki", "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_static("/showkuroki/", os.path.join(HERE, "web", "showkuroki"))
    a.router.add_static("/img", os.path.join(HERE, "web", "img"))   # las fuentes
    return a


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=PUERTO)
    x = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    web.run_app(app(), host="127.0.0.1", port=x.puerto, print=None)
