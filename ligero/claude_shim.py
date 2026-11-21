"""Un llama-server falso que contesta con Claude Code (`claude -p`, el modelo más barato) para el perfil «ligero» de las
dolls: así el agente no cambia ni una línea (sigue hablando OpenAI /v1/chat/completions con LLM_URL) y la GPU queda libre.

  .venv/bin/python -m ligero.claude_shim [--puerto 8086] [--modelo haiku] [--tope-hora 400]

- Usa tu sesión de Claude Code (suscripción), sin clave de API. Sin pensamiento extendido (MAX_THINKING_TOKENS=0): ~2 s.
- Sin herramientas, sin CLAUDE.md, sin MCP, sin sesión guardada: cada pedido es un `claude -p` limpio.
- Streaming: los text_delta de `--include-partial-messages` salen como SSE de OpenAI, para que la voz empiece rápido.
- Tope por hora (`--tope-hora`): pasado ese número de pedidos contesta 429 y el agente degrada (como si el LLM se cayera).
- Solo para el modo SFW: dolls.sh no deja prender `--ligero` sin `--sfw`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from collections import deque

from aiohttp import web

log = logging.getLogger("ligero.shim")
CWD = tempfile.mkdtemp(prefix="claude_shim_")   # vacío: que claude no lea ningún CLAUDE.md ni proyecto


def armar(messages: list[dict], schema: dict | None) -> tuple[str, str]:
    """(system, prompt) para `claude -p`. Los system van al system prompt; el resto, como transcripción."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and isinstance(m.get("content"), str))
    turnos = [m for m in messages if m["role"] != "system"]
    if len(turnos) == 1 and turnos[0]["role"] == "user":
        prompt = turnos[0]["content"]
    else:
        lineas = [f"[{'user' if m['role'] == 'user' else 'assistant'}]\n{m['content']}" for m in turnos]
        prompt = "Conversación hasta ahora:\n\n" + "\n\n".join(lineas) + "\n\nEscribí SOLO el próximo mensaje de assistant."
    if schema:
        prompt += ("\n\nRespondé ÚNICAMENTE con un objeto JSON válido (sin texto alrededor, sin ```), que cumpla este esquema:\n"
                   + json.dumps(schema, ensure_ascii=False))
    return system, prompt


class Shim:
    def __init__(self, modelo: str, tope_hora: int, concurrencia: int):
        self.modelo, self.tope = modelo, tope_hora
        self.sem = asyncio.Semaphore(concurrencia)
        self.pedidos: deque[float] = deque()    # instantes de los últimos pedidos (ventana de 1 h)
        self.total = 0

    def _cupo(self) -> bool:
        ahora = time.monotonic()
        while self.pedidos and ahora - self.pedidos[0] > 3600:
            self.pedidos.popleft()
        return not self.tope or len(self.pedidos) < self.tope

    async def _claude(self, system: str, prompt: str):
        """Corre `claude -p` y va cediendo trozos de texto."""
        env = {**os.environ, "MAX_THINKING_TOKENS": "0", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--model", self.modelo, "--tools", "", "--no-session-persistence", "--setting-sources", "",
            "--disable-slash-commands", "--strict-mcp-config", "--system-prompt", system or "Sos un asistente conciso.",
            "--output-format", "stream-json", "--include-partial-messages", "--verbose",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=CWD, env=env, limit=1 << 22)
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        vio_texto, final = False, ""
        try:
            async for linea in proc.stdout:
                try:
                    o = json.loads(linea)
                except ValueError:
                    continue
                if o.get("type") == "stream_event":
                    d = (o.get("event") or {}).get("delta") or {}
                    if d.get("type") == "text_delta" and d.get("text"):
                        vio_texto = True
                        yield d["text"]
                elif o.get("type") == "result":
                    if o.get("is_error"):
                        raise RuntimeError(str(o.get("result"))[:200])
                    final = o.get("result") or ""
            await proc.wait()
            if not vio_texto and final:
                yield final
            elif not vio_texto and proc.returncode:
                raise RuntimeError((await proc.stderr.read()).decode(errors="replace")[:200])
        finally:
            if proc.returncode is None:
                proc.kill()

    async def completar(self, req: web.Request) -> web.StreamResponse:
        body = await req.json()
        if not self._cupo():
            return web.json_response({"error": {"message": f"tope de {self.tope} pedidos/hora alcanzado"}}, status=429)
        self.pedidos.append(time.monotonic())
        self.total += 1
        schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("schema")
        system, prompt = armar(body["messages"], schema)
        if os.getenv("SHIM_DUMP"):   # diagnóstico: el último pedido completo, para ver qué le llega a Claude
            with open(os.getenv("SHIM_DUMP"), "w") as f:
                f.write("=== SYSTEM ===\n" + system + "\n=== PROMPT ===\n" + prompt)
        t0, idc = time.monotonic(), "chatcmpl-" + uuid.uuid4().hex[:12]
        log.info("#%d %s · %d car. de system · %d de prompt%s · %d en la última hora", self.total, self.modelo,
                 len(system), len(prompt), " · json" if schema else "", len(self.pedidos))

        def chunk(delta: dict, fin: str | None = None) -> bytes:
            o = {"id": idc, "object": "chat.completion.chunk", "model": self.modelo,
                 "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
            return b"data: " + json.dumps(o, ensure_ascii=False).encode() + b"\n\n"

        async with self.sem:
            if body.get("stream"):
                resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
                await resp.prepare(req)
                try:
                    async for t in self._claude(system, prompt):
                        await resp.write(chunk({"content": t}))
                except RuntimeError as e:
                    log.warning("claude falló: %s", e)
                    await resp.write(b"data: " + json.dumps({"error": {"message": str(e)}}).encode() + b"\n\n")
                except ConnectionResetError:
                    return resp     # el agente cortó el stream (la doll fue interrumpida)
                await resp.write(chunk({}, "stop") + b"data: [DONE]\n\n")
                log.info("   listo en %.1f s", time.monotonic() - t0)
                return resp
            try:
                texto = "".join([t async for t in self._claude(system, prompt)])
            except RuntimeError as e:
                log.warning("claude falló: %s", e)
                return web.json_response({"error": {"message": str(e)}}, status=502)
        log.info("   listo en %.1f s", time.monotonic() - t0)
        return web.json_response({"id": idc, "object": "chat.completion", "model": self.modelo, "choices": [
            {"index": 0, "message": {"role": "assistant", "content": texto.strip()}, "finish_reason": "stop"}]})

    async def health(self, _req: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "modelo": self.modelo, "ultima_hora": len(self.pedidos),
                                  "tope_hora": self.tope, "total": self.total})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8086)
    ap.add_argument("--modelo", default=os.getenv("CLAUDE_MODELO", "haiku"), help="alias de claude: haiku (el más barato), sonnet…")
    ap.add_argument("--tope-hora", type=int, default=400, help="pedidos por hora como máximo (0 = sin tope)")
    ap.add_argument("--concurrencia", type=int, default=2)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    s = Shim(a.modelo, a.tope_hora, a.concurrencia)
    app = web.Application()
    app.router.add_post("/v1/chat/completions", s.completar)
    app.router.add_get("/health", s.health)     # /props no existe: el agente entiende «un solo slot», sin ceba de caché
    log.info("shim de Claude Code (%s) en 127.0.0.1:%d · tope %d/h", a.modelo, a.puerto, a.tope_hora)
    web.run_app(app, host="127.0.0.1", port=a.puerto, print=None)


if __name__ == "__main__":
    main()
