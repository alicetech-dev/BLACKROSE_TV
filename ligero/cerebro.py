"""CEREBRO de BlackRose: router failsafe de LLM 100 % local (nada de Claude, Grok ni APIs de pago).

  .venv/bin/python -m ligero.cerebro [--puerto 8087]

Todo lo que antes hablaba con :8087 (agente de las dolls, productor, director de TV, Japón) sigue igual: este router
elige a quién mandarle cada pedido y, si uno se cae, pasa al siguiente sin que el que pregunta se entere.

  rapido   (default; tareas ejecutivas: guiones, chat, JSON)   → 4B en la RTX (:8089)  → 9B del ThinkPad (CPU)
  profundo (pensamientos no dichos, coordinación, investigación) → 9B del ThinkPad      → 4B en la RTX

Se pide «profundo» con "model": "profundo" en el cuerpo o la cabecera X-Cerebro: profundo.
Si ningún backend contesta → 503, y el que pregunta usa su diccionario de decisiones / plantillas (la emisión no se cae).
Salud: GET /health → estado de cada backend y contadores.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time

import aiohttp
from aiohttp import web

log = logging.getLogger("cerebro")
B = {
    "4b": os.getenv("CEREBRO_4B", "http://127.0.0.1:8089"),          # llm4b.service (Agents-A1-4B, RTX)
    "9b": os.getenv("CEREBRO_9B", "http://192.168.1.6:8095"),        # llm9b en el ThinkPad (DeepSeek-V4 9B MTP, CPU)
}
ORDEN = {"rapido": ["4b", "9b"], "profundo": ["9b", "4b"]}
PRIMER_BYTE = {"4b": 40.0, "9b": 1500.0, "grok": 60.0}     # el ThinkPad por CPU es lento: se le espera más
# VENTANA GROK (pedido 2026-11-20: «usa Grok las primeras 2 horas para alivianar al LLM»): mientras logs/grok_hasta tenga una
# hora (epoch) futura, Grok (xAI, API de pago de Alice) va PRIMERO en rapido y profundo; si falla, sigue el orden local de siempre.
GROK_HASTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "grok_hasta")
XAI = "https://api.x.ai/v1/chat/completions"
GROK_MODELO = os.getenv("GROK_MODEL", "grok-4.20-0309-non-reasoning")
GROK_CAMPOS = {"messages", "temperature", "max_tokens", "stream", "response_format", "top_p", "stop", "seed"}


def grok_activo() -> bool:
    try:
        return time.time() < float(open(GROK_HASTA).read().strip())
    except (OSError, ValueError):
        return False


class Cerebro:
    def __init__(self):
        self.s: aiohttp.ClientSession | None = None
        self.sano: dict[str, tuple[bool, float]] = {}
        self.ocupado = {k: 0 for k in B}
        self.n = {f"{k}:{x}": 0 for k in B for x in ("ok", "falla")}

    async def vivo(self, k: str) -> bool:
        v, t = self.sano.get(k, (False, 0.0))
        if time.monotonic() - t < 3:
            return v
        try:
            async with self.s.get(B[k] + "/health", timeout=aiohttp.ClientTimeout(total=2)) as r:
                v = r.status == 200
        except Exception:  # noqa: BLE001
            v = False
        self.sano[k] = (v, time.monotonic())
        return v

    def modo(self, req: web.Request, cuerpo: dict) -> str:
        m = (req.headers.get("X-Cerebro") or str(cuerpo.get("model") or "")).lower()
        return "profundo" if "profundo" in m or "9b" in m else "rapido"

    async def completar(self, req: web.Request) -> web.StreamResponse:
        crudo = await req.read()
        try:
            cuerpo = json.loads(crudo)
        except ValueError:
            return web.json_response({"error": {"message": "JSON inválido"}}, status=400)
        modo = self.modo(req, cuerpo)
        orden = [k for k in ORDEN[modo] if await self.vivo(k)]
        if grok_activo():
            r = await self._grok(req, dict(cuerpo))
            if r is not None:
                return r
        # rápido: si el 4B está atendiendo 2 pedidos (sus 2 slots) y el 9B está libre, no se encola: va al 9B
        if modo == "rapido" and len(orden) == 2 and self.ocupado["4b"] >= 2 and self.ocupado["9b"] == 0 and int(cuerpo.get("max_tokens") or 0) <= 300:
            orden.reverse()
        if modo == "profundo":
            cuerpo.setdefault("max_tokens", 700)
        cuerpo.pop("model", None)
        for k in orden:
            r = await self._probar(req, k, cuerpo)
            if r is not None:
                return r
        return web.json_response({"error": {"message": "cerebro: ningún LLM local disponible"}}, status=503)

    async def _probar(self, req: web.Request, k: str, cuerpo: dict) -> web.StreamResponse | None:
        stream = bool(cuerpo.get("stream"))
        self.ocupado[k] += 1
        try:
            r = await self.s.post(B[k] + "/v1/chat/completions", json=cuerpo,
                                  timeout=aiohttp.ClientTimeout(total=None, sock_connect=3, sock_read=PRIMER_BYTE[k]))
        except Exception as e:  # noqa: BLE001
            self.ocupado[k] -= 1
            self._falla(k, f"no conecta ({type(e).__name__})")
            return None
        try:
            async with r:
                if r.status >= 500:
                    self._falla(k, f"respondió {r.status}")
                    return None
                if not stream:
                    datos = await r.read()
                    self.n[f"{k}:ok"] += 1
                    return web.Response(body=datos, status=r.status, content_type="application/json", headers={"X-Cerebro-Backend": k})
                resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Cerebro-Backend": k})
                primero = True
                try:
                    async for trozo in r.content.iter_any():
                        if primero:
                            await resp.prepare(req)
                            primero = False
                        await resp.write(trozo)
                except Exception as e:  # noqa: BLE001
                    if primero:
                        self._falla(k, f"sin primer byte ({type(e).__name__})")
                        return None
                    log.warning("%s: el stream se cortó a mitad: %s", k, e)
                if primero:
                    self._falla(k, "respuesta vacía")
                    return None
                self.n[f"{k}:ok"] += 1
                return resp
        except Exception as e:  # noqa: BLE001
            self._falla(k, f"{type(e).__name__}: {e}")
            return None
        finally:
            self.ocupado[k] -= 1

    async def _grok(self, req: web.Request, cuerpo: dict) -> web.StreamResponse | None:
        from .grok_shim import clave
        p = {k: v for k, v in cuerpo.items() if k in GROK_CAMPOS}
        p["model"] = GROK_MODELO
        p["stream"] = False                    # simple y robusto: si el cliente pidió stream se le manda un solo trozo SSE
        p.setdefault("max_tokens", 900)
        self.ocupado.setdefault("grok", 0)
        self.ocupado["grok"] += 1
        try:
            for intento in range(2):
                async with self.s.post(XAI, json=p, headers={"Authorization": f"Bearer {clave()}"},
                                       timeout=aiohttp.ClientTimeout(total=PRIMER_BYTE["grok"])) as r:
                    datos = await r.read()
                    if r.status == 400 and "response_format" in p:
                        p.pop("response_format")
                        continue
                    if r.status != 200:
                        self._falla("grok", f"respondió {r.status}: {datos[:120]!r}")
                        return None
                break
            self.n["grok:ok"] = self.n.get("grok:ok", 0) + 1
            if not cuerpo.get("stream"):
                return web.Response(body=datos, status=200, content_type="application/json", headers={"X-Cerebro-Backend": "grok"})
            d = json.loads(datos)
            txt = d["choices"][0]["message"].get("content") or ""
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Cerebro-Backend": "grok"})
            await resp.prepare(req)
            await resp.write(("data: " + json.dumps({"choices": [{"index": 0, "delta": {"role": "assistant", "content": txt}, "finish_reason": None}]}) + "\n\n").encode())
            await resp.write(("data: " + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\ndata: [DONE]\n\n").encode())
            return resp
        except Exception as e:  # noqa: BLE001
            self._falla("grok", f"{type(e).__name__}: {e}")
            return None
        finally:
            self.ocupado["grok"] -= 1

    def _falla(self, k: str, motivo: str) -> None:
        self.n[f"{k}:falla"] = self.n.get(f"{k}:falla", 0) + 1
        self.sano[k] = (False, time.monotonic())
        log.warning("%s falló (%s): paso al siguiente", k, motivo)

    async def health(self, _req: web.Request) -> web.Response:
        est = {k: await self.vivo(k) for k in B}
        if grok_activo():
            est["grok"] = True
        return web.json_response({"status": "ok" if any(est.values()) else "caido", "backends": est, "urls": B,
                                  "grok_hasta": time.strftime("%H:%M", time.localtime(float(open(GROK_HASTA).read()))) if grok_activo() else None,
                                  "ocupado": self.ocupado, "pedidos": self.n}, status=200 if any(est.values()) else 503)

    async def pasar(self, req: web.Request) -> web.Response:
        for k in ("4b", "9b"):
            if await self.vivo(k):
                try:
                    async with self.s.request(req.method, B[k] + req.path_qs, data=await req.read(), timeout=aiohttp.ClientTimeout(total=10)) as r:
                        return web.Response(body=await r.read(), status=r.status, content_type=r.content_type)
                except Exception:  # noqa: BLE001
                    continue
        return web.json_response({"error": "sin LLM"}, status=404)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8087)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    c = Cerebro()
    app = web.Application(client_max_size=64 * 1024 * 1024)

    async def abrir(_):
        c.s = aiohttp.ClientSession()

    async def cerrar(_):
        await c.s.close()
    app.on_startup.append(abrir)
    app.on_cleanup.append(cerrar)
    app.router.add_post("/v1/chat/completions", c.completar)
    app.router.add_get("/health", c.health)
    app.router.add_route("*", "/{tail:.*}", c.pasar)
    log.info("cerebro en :%d → %s", a.puerto, B)
    web.run_app(app, host="127.0.0.1", port=a.puerto, print=None)


if __name__ == "__main__":
    main()
