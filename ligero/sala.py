"""Sala 3D de BlackRose TV: Joy y Kuroki dentro de un mundo WebGL (fuente Navegador de OBS, 1920×1080).

Dos entornos de BIMBOLAND, en versión SAFE (sin Bambi, sin carteles ni cosas adultas):
  · «hacker»  la pieza hacker de Barbie Blackrose (shoji + jardín japonés, arcade, sillón neural). Sus 3 monitores son la
              SALA DE CONTROL del canal: al aire, cartelera y chat. (no muestran datos del PC ni procesos)
  · «joy»     el cuarto de Joy del Bimbo Institute (cama, tocador, escritorio, tele con el canal), sin el cartel «69».
Los cuerpos llegan por el eco VMC que ya consumen los overlays :8810 (Joy) y :8811 (Kuroki): esta página se conecta a esos
WebSockets, así que no compite por los puertos UDP. Si no hay VMC (stack parado) quedan en pose de reposo.
La cámara hace planos solos y se acerca a quien habla (WebSocket del director :8780).

  .venv/bin/python -m ligero.sala [--puerto 8830]
  http://127.0.0.1:8830/?sala=hacker|joy  ?cam=auto|jardin|control|sillon|joy|kuroki  ?fps=30  ?calidad=1
  POST /api/sala {"sala":"joy"}  → cambia de entorno en vivo (lo lee la página cada 2 s) · GET /api/sala
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import aiohttp
from aiohttp import web

HERE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(HERE)
log = lambda *a: print(time.strftime("%H:%M:%S"), *a, flush=True)

VRM = {
    "joy": os.path.expanduser("~/Joy_SFW_fix.vrm"),
    "kuroki": os.path.expanduser("~/Kuroki_VRM/Kuroki_EFBodysuit_twitch.vrm"),
    "yo": os.path.expanduser("~/BambiBarbie.vrm"),      # Alice/Barbie Blackrose: la que duerme en la cámara de circuito cerrado (tapada hasta el cuello)
}
TV = "http://127.0.0.1:8822"
ESTADO_F = os.path.join(RAIZ, "director", "tv", "sala.json")
SUENO_F = os.path.join(RAIZ, "director", "tv", "sueno.json")
SALAS = ("hacker", "joy")
SIN_CACHE = {"Cache-Control": "no-cache"}
MEDIOS = os.path.join(RAIZ, "director", "tv", "medios")


class Sala:
    def __init__(self, a):
        self.a = a
        self.sala = "hacker"
        try:
            s = json.load(open(ESTADO_F)).get("sala")
            if s in SALAS:
                self.sala = s
        except (OSError, ValueError):
            pass
        self.cache: dict[str, tuple[float, bytes]] = {}
        self.medio: dict | None = None            # la foto/nota que el director muestra en las pantallas (vence sola)
        self.http: aiohttp.ClientSession | None = None

    async def proxy(self, req: web.Request) -> web.Response:
        """/api/tv, /api/chat, /api/cartelera del overlay del canal (:8822), con 2 s de caché y sin CORS."""
        ruta = "/api/" + req.match_info["r"]
        if req.match_info["r"] not in ("tv", "chat", "cartelera"):
            raise web.HTTPNotFound()
        t, cuerpo = self.cache.get(ruta, (0, b"null"))
        if time.time() - t > 2:
            try:
                async with self.http.get(TV + ruta, timeout=aiohttp.ClientTimeout(total=3)) as r:
                    cuerpo = await r.read()
                self.cache[ruta] = (time.time(), cuerpo)
            except Exception:
                pass
        return web.Response(body=cuerpo, content_type="application/json", headers=SIN_CACHE)

    async def get_sala(self, _req: web.Request) -> web.Response:
        if self.medio and time.time() > self.medio.get("hasta", 0):
            self.medio = None
        return web.json_response({"sala": self.sala, "salas": list(SALAS), "medio": self.medio}, headers=SIN_CACHE)

    async def post_medio(self, req: web.Request) -> web.Response:
        """{"img":"/medios/x.jpg","titulo":"...","credito":"...","clase":"noticia","seg":90} · {} o {"quitar":true} lo saca."""
        try:
            d = await req.json()
        except ValueError:
            d = {}
        self.medio = None if d.get("quitar") or not (d.get("titulo") or d.get("img")) else {
            "img": d.get("img"), "titulo": str(d.get("titulo", ""))[:140], "credito": str(d.get("credito", ""))[:120], "clase": d.get("clase", ""),
            "hasta": time.time() + min(float(d.get("seg", 120)), 600)}
        return web.json_response({"ok": True})

    async def post_sala(self, req: web.Request) -> web.Response:
        try:
            d = await req.json()
        except ValueError:
            return web.json_response({"ok": False}, status=400)
        s = d.get("sala")
        if s not in SALAS:
            return web.json_response({"ok": False, "error": f"sala ∈ {SALAS}"}, status=400)
        self.sala = s
        try:
            json.dump({"sala": s}, open(ESTADO_F, "w"))
        except OSError:
            pass
        return web.json_response({"ok": True, "sala": s})

    def _sueno(self) -> dict:
        try:
            d = json.load(open(SUENO_F))
        except (OSError, ValueError):
            d = {}
        despierta = float(d.get("despierta") or 0)
        return {"dormida": bool(d.get("dormida")) and despierta > time.time(), "despierta": despierta, "desde": d.get("desde", 0), "ahora": time.time()}

    async def get_sueno(self, _req: web.Request) -> web.Response:
        return web.json_response(self._sueno(), headers=SIN_CACHE)

    async def post_sueno(self, req: web.Request) -> web.Response:
        """{"minutos": 180} · {"hasta": "07:30"} · {"dormida": false} (despierta ya)."""
        try:
            d = await req.json()
        except ValueError:
            return web.json_response({"ok": False}, status=400)
        ahora = time.time()
        if d.get("dormida") is False:
            nuevo = {"dormida": False, "despierta": 0, "desde": 0}
        elif d.get("hasta"):
            try:
                h, m = map(int, str(d["hasta"]).split(":"))
            except ValueError:
                return web.json_response({"ok": False, "error": "hasta = HH:MM"}, status=400)
            t = time.localtime(ahora); fin = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, m, 0, 0, 0, -1))
            if fin <= ahora:
                fin += 86400
            nuevo = {"dormida": True, "despierta": fin, "desde": ahora}
        elif d.get("minutos"):
            nuevo = {"dormida": True, "despierta": ahora + float(d["minutos"]) * 60, "desde": ahora}
        else:
            return web.json_response({"ok": False, "error": "minutos, hasta o dormida:false"}, status=400)
        try:
            json.dump(nuevo, open(SUENO_F, "w"))
        except OSError:
            pass
        return web.json_response({"ok": True, **self._sueno()})

    def modelo(self, quien: str):
        async def h(_r: web.Request) -> web.StreamResponse:
            return web.FileResponse(VRM[quien], headers=SIN_CACHE)
        return h

    async def iniciar(self, host: str, puerto: int) -> None:
        for q, f in VRM.items():
            if not os.path.exists(f):
                log(f"aviso: falta el VRM de {q}: {f}")
        self.http = aiohttp.ClientSession()
        app = web.Application()
        pagina = lambda r: web.FileResponse(os.path.join(HERE, "web", "sala.html"), headers=SIN_CACHE)
        app.router.add_get("/", pagina)
        app.router.add_get("/insignia", lambda r: web.FileResponse(os.path.join(HERE, "web", "insignia.html"), headers=SIN_CACHE))
        app.router.add_get("/api/sala", self.get_sala)
        app.router.add_post("/api/sala", self.post_sala)
        app.router.add_post("/api/medio", self.post_medio)
        os.makedirs(MEDIOS, exist_ok=True)
        app.router.add_static("/medios/", MEDIOS, show_index=False)
        app.router.add_get("/api/sueno", self.get_sueno)
        app.router.add_post("/api/sueno", self.post_sueno)
        app.router.add_get("/api/{r}", self.proxy)
        for q in VRM:
            app.router.add_get(f"/{q}.vrm", self.modelo(q))
        # la pieza hacker y el cuarto de Joy se arman con los módulos del juego (se leen tal cual, sin copiarlos)
        app.router.add_static("/mundo/", os.path.join(RAIZ, "vr", "web"), show_index=False)
        app.router.add_static("/sala/", os.path.join(HERE, "web", "sala"), show_index=False)
        app.router.add_static("/vendor/", os.path.join(HERE, "web", "vendor"), show_index=False)
        # lo que hacker.js pide al servidor del juego: aquí, nada (sin datos del PC ni pósters)
        app.router.add_get("/hacker/sistema", lambda r: web.json_response({}))
        app.router.add_get("/hacker/posters", lambda r: web.json_response({"n": 0}))
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, host, puerto).start()
        log(f"sala 3D: http://{host}:{puerto}/?sala={self.sala}")
        while True:
            await asyncio.sleep(3600)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8830)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    try:
        asyncio.run(Sala(a).iniciar(a.host, a.puerto))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
