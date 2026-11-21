"""Clientes WebSocket: el cuerpo (joy_vmc de cada doll) y el cerebro (`python -m agente serve` / `run` con
DOLL_SERVE_PORT). Se reconectan solos: si uno se cae, la doll sigue (quieta o dormida) en vez de morir."""
from __future__ import annotations

import asyncio
import itertools
import json
import logging

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

log = logging.getLogger("director.clientes")


class Cuerpo:
    """joy_vmc: cada intención recibe una respuesta {"ok": ...}. Los RMS (50/s) se mandan sin esperar respuesta."""

    def __init__(self, url: str):
        self.url, self.ws, self.lock = url, None, asyncio.Lock()
        self._lector: asyncio.Task | None = None
        self._pend: asyncio.Queue = asyncio.Queue()

    async def _asegurar(self) -> bool:
        if self.ws is not None:
            return True
        try:
            self.ws = await connect(self.url, open_timeout=2, max_queue=None)
            self._lector = asyncio.create_task(self._leer())
            return True
        except (OSError, WebSocketException, asyncio.TimeoutError) as e:
            log.warning("sin cuerpo en %s: %s", self.url, e)
            return False

    async def _leer(self):
        try:
            async for raw in self.ws:
                fut = await self._pend.get()
                if fut is not None and not fut.done():
                    fut.set_result(json.loads(raw))
        except WebSocketException:
            pass
        finally:
            self.ws = None
            while not self._pend.empty():
                fut = self._pend.get_nowait()
                if fut is not None and not fut.done():
                    fut.set_result({"ok": False, "error": "desconectado"})

    async def enviar(self, d: dict, esperar: bool = True) -> dict:
        async with self.lock:
            if not await self._asegurar():
                return {"ok": False, "error": "sin conexión"}
            fut = asyncio.get_running_loop().create_future() if esperar else None
            await self._pend.put(fut)
            try:
                await self.ws.send(json.dumps(d, ensure_ascii=False))
            except WebSocketException as e:
                return {"ok": False, "error": str(e)}
        if not esperar:
            return {"ok": True}
        try:
            r = await asyncio.wait_for(fut, 3)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "timeout"}
        if not r.get("ok"):
            log.info("joy_vmc rechazó %s: %s", d, r.get("error"))
        return r

    def rms(self, valor: float) -> None:
        asyncio.get_running_loop().create_task(self.enviar({"rms": round(valor, 4)}, esperar=False))


class Cerebro:
    """Agente: pedidos con "req"; las respuestas de varios pedidos pueden llegar intercaladas."""

    def __init__(self, url: str, al_evento=None):
        self.url, self.ws = url, None
        self.al_evento = al_evento  # eventos sin pedido (segmentos de autonomía): callback(ev)
        self.colas: dict[int, asyncio.Queue] = {}
        self.ids = itertools.count(1)
        self.lock = asyncio.Lock()

    async def _asegurar(self):
        async with self.lock:
            if self.ws is None:
                self.ws = await connect(self.url, open_timeout=3, max_size=None, ping_interval=20)
                asyncio.create_task(self._leer())

    async def _leer(self):
        ws = self.ws
        try:
            async for raw in ws:
                ev = json.loads(raw)
                q = self.colas.get(ev.get("req"))
                if q:
                    q.put_nowait(ev)
                elif ev.get("req") is None and self.al_evento:
                    self.al_evento(ev)
        except WebSocketException:
            pass
        finally:
            self.ws = None
            for q in self.colas.values():
                q.put_nowait({"type": "error", "error": "se cortó la conexión con el agente", "sleeping": True})

    async def eventos(self, msg: dict):
        """Manda un pedido y va cediendo sus eventos hasta done/error (o la respuesta única de un cmd)."""
        try:
            await self._asegurar()
        except (OSError, WebSocketException, asyncio.TimeoutError) as e:
            yield {"type": "error", "error": f"agente no disponible en {self.url}: {e}", "sleeping": True}
            return
        req = next(self.ids)
        q = self.colas[req] = asyncio.Queue()
        try:
            await self.ws.send(json.dumps({**msg, "req": req}, ensure_ascii=False))
            while True:
                ev = await q.get()
                yield ev
                if ev.get("type") in ("done", "error") or "cmd" in msg:
                    return
        finally:
            self.colas.pop(req, None)

    async def conectar(self) -> None:
        """Conecta ya (para recibir los segmentos de autonomía aunque todavía no se haya pedido nada)."""
        try:
            await self._asegurar()
        except (OSError, WebSocketException, asyncio.TimeoutError) as e:
            log.warning("agente no disponible en %s: %s", self.url, e)

    async def pedir(self, msg: dict) -> dict:
        async for ev in self.eventos(msg):
            return ev
        return {"type": "error", "error": "sin respuesta"}
