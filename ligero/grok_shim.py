"""Un llama-server falso que contesta con Grok (xAI, en la nube): el agente sigue hablando OpenAI /v1/chat/completions
con LLM_URL y la GPU queda libre para Warudo/OBS.

  .venv/bin/python -m ligero.grok_shim [--puerto 8087] [--modelo grok-4.20-0309-non-reasoning]

- La clave sale de GROK_API_KEY o de ~/.env (nunca se loguea).
- Saca los campos propios de llama.cpp (id_slot, cache_prompt, DRY, chat_template_kwargs…) antes de reenviar.
- /health y /props contestan solos (1 slot); /apply-template, /tokenize y /completion dan 404: el agente no ceba nada.
- Streaming SSE: se reenvía tal cual llega.
"""
from __future__ import annotations

import argparse
import logging
import os

import httpx
from aiohttp import web

log = logging.getLogger("ligero.grok")
XAI = "https://api.x.ai/v1/chat/completions"
PERMITIDOS = {"messages", "temperature", "max_tokens", "stream", "response_format", "top_p", "stop", "seed"}


def clave() -> str:
    k = os.getenv("GROK_API_KEY", "")
    if not k:
        try:
            for ln in open(os.path.expanduser("~/.env"), encoding="utf-8"):
                if ln.startswith("GROK_API_KEY="):
                    k = ln.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
    return k


def app(modelo: str) -> web.Application:
    cli = httpx.AsyncClient(timeout=httpx.Timeout(15, read=120))
    hdr = {"Authorization": f"Bearer {clave()}"}
    a = web.Application()

    async def health(_):
        return web.json_response({"status": "ok"})

    async def props(_):
        return web.json_response({"total_slots": 1})

    async def chat(req: web.Request):
        body = await req.json()
        p = {k: v for k, v in body.items() if k in PERMITIDOS}
        p["model"] = modelo
        if not p.get("stream"):
            r = await cli.post(XAI, json=p, headers=hdr)
            if r.status_code == 400 and "response_format" in p:   # esquema no aceptado: sin restricción
                p.pop("response_format")
                r = await cli.post(XAI, json=p, headers=hdr)
            if r.status_code != 200:
                log.warning("xai %s: %s", r.status_code, r.text[:200])
            return web.Response(body=r.content, status=r.status_code, content_type="application/json")
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        async with cli.stream("POST", XAI, json=p, headers=hdr) as r:
            if r.status_code != 200:
                txt = (await r.aread()).decode(errors="replace")
                log.warning("xai %s: %s", r.status_code, txt[:200])
                return web.Response(text=txt, status=r.status_code)
            await resp.prepare(req)
            async for trozo in r.aiter_raw():
                await resp.write(trozo)
        await resp.write_eof()
        return resp

    a.router.add_get("/health", health)
    a.router.add_get("/props", props)
    a.router.add_post("/v1/chat/completions", chat)
    return a


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8087)
    ap.add_argument("--modelo", default=os.getenv("GROK_MODEL", "grok-4.20-0309-non-reasoning"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    web.run_app(app(a.modelo), host="127.0.0.1", port=a.puerto, print=None)
