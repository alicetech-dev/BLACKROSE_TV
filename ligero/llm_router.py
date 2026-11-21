"""Router de LLM para Joy: el 9B local es el cerebro; si no puede (apagado, ocupado, la GPU la tiene ComfyUI), contesta Claude
(el shim `claude -p`, haiku) para que nunca falle, con un tope SEMANAL de tokens.

  .venv/bin/python -m ligero.llm_router [--puerto 8087] [--llama http://127.0.0.1:8085] [--claude http://127.0.0.1:8086]
                                        [--tope-semanal 1500000]

El agente habla con ESTE puerto (LLM_URL). Reglas por pedido:
  1. Si existe el archivo-bandera `logs/gpu_comfy` (ComfyUI está generando una imagen y el 9B está apagado) → Claude.
  2. Si el 9B no responde /health, o ya hay otro pedido en curso (un solo slot) → Claude.
  3. Si el 9B falla antes de dar el primer byte → ese pedido se repite en Claude.
  4. Si el tope semanal de Claude se agotó → no se usa Claude (se insiste con el 9B / error 503 si está apagado).
El gasto se estima (≈3,5 car/token, entrada + salida) y se guarda en logs/claude_semana.json (se reinicia cada semana ISO).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import date

import aiohttp
from aiohttp import web

log = logging.getLogger("ligero.router")
HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(os.path.dirname(HERE), "logs")
BANDERA = os.path.join(LOGS, "gpu_comfy")
GASTO = os.path.join(LOGS, "claude_semana.json")


def semana() -> str:
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


class Router:
    def __init__(self, llama: str, claude: str, tope: int, primer_byte: float):
        self.llama, self.claude, self.tope, self.primer_byte = llama.rstrip("/"), claude.rstrip("/"), tope, primer_byte
        self.en_curso = 0
        self._sano, self._sano_t = True, 0.0
        self.n = {"llama": 0, "claude": 0, "fallback": 0}
        self.s: aiohttp.ClientSession | None = None

    # ---- presupuesto semanal ----
    def gastado(self) -> int:
        try:
            d = json.load(open(GASTO))
            return d["tokens"] if d.get("semana") == semana() else 0
        except (OSError, ValueError, KeyError):
            return 0

    def sumar(self, tokens: int) -> None:
        os.makedirs(LOGS, exist_ok=True)
        json.dump({"semana": semana(), "tokens": self.gastado() + int(tokens)}, open(GASTO, "w"))

    def hay_cupo(self) -> bool:
        return not self.tope or self.gastado() < self.tope

    # ---- salud del 9B ----
    async def llama_sano(self) -> bool:
        if os.path.exists(BANDERA):
            return False
        if time.monotonic() - self._sano_t < 2:
            return self._sano
        try:
            async with self.s.get(self.llama + "/health", timeout=aiohttp.ClientTimeout(total=1.5)) as r:
                self._sano = r.status == 200
        except Exception:  # noqa: BLE001
            self._sano = False
        self._sano_t = time.monotonic()
        return self._sano

    # ---- Claude ----
    async def por_claude(self, req: web.Request, cuerpo: bytes, motivo: str) -> web.StreamResponse:
        self.n["claude"] += 1
        entrada = len(cuerpo)
        log.info("→ Claude (%s) · %d/%d tokens esta semana", motivo, self.gastado(), self.tope)
        stream = bool(json.loads(cuerpo).get("stream"))
        async with self.s.post(self.claude + "/v1/chat/completions", data=cuerpo, headers={"Content-Type": "application/json"},
                               timeout=aiohttp.ClientTimeout(total=170)) as r:
            if not stream:
                datos = await r.read()
                self.sumar((entrada + len(datos)) / 3.5)
                return web.Response(body=datos, status=r.status, content_type="application/json")
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
            await resp.prepare(req)
            salida = 0
            async for trozo in r.content.iter_any():
                salida += len(trozo)
                await resp.write(trozo)
            self.sumar((entrada + salida * 0.4) / 3.5)   # el SSE lleva mucho envoltorio: ~40 % es texto
            return resp

    # ---- /v1/chat/completions ----
    async def completar(self, req: web.Request) -> web.StreamResponse:
        cuerpo = await req.read()
        usar_claude = None
        if not await self.llama_sano():
            usar_claude = "9B apagado/GPU ocupada"
        elif self.en_curso >= 1:
            usar_claude = "9B ocupado"
        if usar_claude:
            if self.hay_cupo():
                try:
                    return await self.por_claude(req, cuerpo, usar_claude)
                except Exception as e:  # noqa: BLE001
                    log.warning("Claude falló (%s)", e)
            if not await self.llama_sano():
                return web.json_response({"error": {"message": "sin LLM disponible"}}, status=503)
        self.en_curso += 1
        try:
            return await self.por_llama(req, cuerpo)
        finally:
            self.en_curso -= 1

    async def por_llama(self, req: web.Request, cuerpo: bytes) -> web.StreamResponse:
        stream = bool(json.loads(cuerpo).get("stream"))
        self.n["llama"] += 1
        try:
            r = await self.s.post(self.llama + "/v1/chat/completions", data=cuerpo, headers={"Content-Type": "application/json"},
                                  timeout=aiohttp.ClientTimeout(total=None, sock_connect=3, sock_read=self.primer_byte))
        except Exception as e:  # noqa: BLE001
            return await self._respaldo(req, cuerpo, f"9B no conecta ({type(e).__name__})")
        async with r:
            if r.status >= 500:
                return await self._respaldo(req, cuerpo, f"9B respondió {r.status}")
            if not stream:
                try:
                    datos = await r.read()
                except Exception as e:  # noqa: BLE001
                    return await self._respaldo(req, cuerpo, f"9B lento ({type(e).__name__})")
                return web.Response(body=datos, status=r.status, content_type="application/json")
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
            primero = True
            try:
                async for trozo in r.content.iter_any():
                    if primero:
                        await resp.prepare(req)
                        primero = False
                    await resp.write(trozo)
            except Exception as e:  # noqa: BLE001
                if primero:
                    return await self._respaldo(req, cuerpo, f"9B sin primer byte ({type(e).__name__})")
                log.warning("el stream del 9B se cortó a mitad: %s", e)
            if primero:
                return await self._respaldo(req, cuerpo, "9B respondió vacío")
            return resp

    async def _respaldo(self, req, cuerpo, motivo) -> web.StreamResponse:
        self.n["fallback"] += 1
        if self.hay_cupo():
            return await self.por_claude(req, cuerpo, motivo)
        return web.json_response({"error": {"message": motivo + " y se agotó el tope semanal de Claude"}}, status=503)

    # ---- el resto (/props, /v1/models…) pasa directo al 9B; /health siempre responde ----
    async def health(self, _req: web.Request) -> web.Response:
        sano = await self.llama_sano()
        return web.json_response({"status": "ok", "backend": "llama" if sano else "claude", "claude_semana": self.gastado(),
                                  "tope_semanal": self.tope, "pedidos": self.n})

    async def pasar(self, req: web.Request) -> web.Response:
        if not await self.llama_sano():
            return web.json_response({"error": "9B no disponible"}, status=404)
        try:
            async with self.s.request(req.method, self.llama + req.path_qs, data=await req.read(),
                                      timeout=aiohttp.ClientTimeout(total=10)) as r:
                return web.Response(body=await r.read(), status=r.status, content_type=r.content_type)
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "9B no disponible"}, status=404)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8087)
    ap.add_argument("--llama", default="http://127.0.0.1:8085")
    ap.add_argument("--claude", default="http://127.0.0.1:8086")
    ap.add_argument("--tope-semanal", type=int, default=int(os.getenv("CLAUDE_TOPE_SEMANAL", "1500000")),
                    help="tokens de Claude por semana ISO como máximo (estimados; 0 = sin tope)")
    ap.add_argument("--primer-byte", type=float, default=25.0, help="segundos sin respuesta del 9B antes de pasar a Claude")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    r = Router(a.llama, a.claude, a.tope_semanal, a.primer_byte)
    app = web.Application(client_max_size=64 * 1024 * 1024)

    async def abrir(_):
        r.s = aiohttp.ClientSession()

    async def cerrar(_):
        await r.s.close()
    app.on_startup.append(abrir)
    app.on_cleanup.append(cerrar)
    app.router.add_post("/v1/chat/completions", r.completar)
    app.router.add_get("/health", r.health)
    app.router.add_route("*", "/{tail:.*}", r.pasar)
    log.info("router LLM en :%d → 9B %s · respaldo Claude %s · tope %d tokens/semana", a.puerto, a.llama, a.claude, a.tope_semanal)
    web.run_app(app, host="127.0.0.1", port=a.puerto, print=None)


if __name__ == "__main__":
    main()
