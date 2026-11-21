"""Joy como overlay VRM para OBS (perfil «ligero»): sin Warudo, sin segundo render pesado.

Recibe el eco VMC de joy_vmc (huesos + cara + boca del lip-sync) y sirve una página three.js + VRM con fondo
transparente. En OBS: fuente *Navegador* → http://127.0.0.1:8810/ (ancho 700 × alto 1080, fondo transparente) encima de la
captura de XR Animator. Parámetros de la URL: ?enc=cuerpo|medio|cara  ?x=0  ?y=0  ?zoom=1  ?fps=30  ?luz=1.0

  .venv/bin/python -m ligero.overlay [--vrm ~/Joy_SFW.vrm] [--vmc 39639] [--puerto 8810]
"""
import argparse
import asyncio
import glob
import json
import os
import random

from aiohttp import web

from vr.servidor import DollVMC

HERE = os.path.dirname(os.path.abspath(__file__))
log = lambda *a: print(*a, flush=True)


class Overlay:
    def __init__(self, vrm: str, vmc_puerto: int, fps: int, baile_auto: float = 0):
        self.vrm, self.fps, self.baile_auto = os.path.expanduser(vrm), fps, baile_auto
        self.joy = DollVMC("joy", vmc_puerto)
        self.clientes: set[web.WebSocketResponse] = set()

    async def emitir(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(1 / self.fps)
            if not self.clientes:
                continue
            msg = json.dumps({"t": "cuadro", "d": self.joy.cuadro(loop.time())})
            for ws in list(self.clientes):
                try:
                    await ws.send_str(msg)
                except Exception:
                    self.clientes.discard(ws)

    async def ws(self, req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        self.clientes.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            self.clientes.discard(ws)
        return ws

    async def auto_baile(self, minutos: float) -> None:
        """Para que no esté estática: cada tanto baila una canción sola (a volumen bajo)."""
        while True:
            await asyncio.sleep(random.uniform(0.7, 1.3) * minutos * 60)
            ids = [os.path.basename(f)[:-5] for f in glob.glob(os.path.join(HERE, "web", "bailes", "*.json"))]
            if ids and self.clientes:
                msg = json.dumps({"t": "baile", "id": random.choice(ids), "musica": True, "vol": 0.35})
                for ws in list(self.clientes):
                    try:
                        await ws.send_str(msg)
                    except Exception:
                        self.clientes.discard(ws)

    async def baile(self, req: web.Request) -> web.Response:
        """POST {"id": "saso", "musica": true}: Joy baila (id vacío = corta). Lo llama el director."""
        try:
            d = await req.json()
        except ValueError:
            return web.json_response({"ok": False}, status=400)
        msg = json.dumps({"t": "baile", "id": str(d.get("id") or ""), "musica": d.get("musica", True), "vol": d.get("vol", 0.6)})
        for ws in list(self.clientes):
            try:
                await ws.send_str(msg)
            except Exception:
                self.clientes.discard(ws)
        return web.json_response({"ok": True, "clientes": len(self.clientes)})

    async def modelo(self, _req: web.Request) -> web.StreamResponse:
        return web.FileResponse(self.vrm, headers={"Cache-Control": "no-cache"})

    async def iniciar(self, host: str, puerto: int) -> None:
        if not os.path.exists(self.vrm):
            raise SystemExit(f"no encuentro el VRM: {self.vrm}")
        await self.joy.escuchar()
        app = web.Application()
        app.router.add_get("/ws", self.ws)
        app.router.add_post("/api/baile", self.baile)
        app.router.add_static("/bailes/", os.path.join(HERE, "web", "bailes"), show_index=False)
        app.router.add_get("/joy.vrm", self.modelo)
        # three.js local (Flatpak OBS no puede bajar el CDN → página transparente)
        app.router.add_static("/vendor/", os.path.join(HERE, "web", "vendor"), show_index=False)
        sin_cache = {"Cache-Control": "no-cache"}
        app.router.add_get("/", lambda r: web.FileResponse(os.path.join(HERE, "web", "joy.html"), headers=sin_cache))
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, host, puerto).start()
        log(f"overlay de Joy: http://{host}:{puerto}/  ({self.vrm})")
        if self.baile_auto:
            asyncio.create_task(self.auto_baile(self.baile_auto))
        await self.emitir()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vrm", default="~/Joy_SFW.vrm")
    ap.add_argument("--vmc", type=int, default=39639, help="puerto del eco VMC de joy_vmc (--eco)")
    ap.add_argument("--puerto", type=int, default=8810)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--baile-auto", type=float, default=0, help="cada ~N minutos baila una canción sola (0 = no)")
    a = ap.parse_args()
    try:
        asyncio.run(Overlay(a.vrm, a.vmc, a.fps, a.baile_auto).iniciar(a.host, a.puerto))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
