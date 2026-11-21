"""Cliente mínimo de la API nativa de Warudo (la misma que usa el MCP `warudo-mcp-server`).

Protocolo: WebSocket a ws://[::1]:19053/ (bajo Proton Warudo escucha solo en IPv6) con el token como subprotocolo.
Se manda {"action", "data": {"id": n, ...}} y llega {"action": <la misma>, "data"|"error"}; una llamada a la vez.
El token cambia en cada arranque de Warudo: se saca del proceso del cliente electron (`--token=`) o, si no está, del
Player.log de Warudo (`One Time API Auth Token`). Nunca se imprime ni se guarda.
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import re
import subprocess

from websockets.asyncio.client import connect

log = logging.getLogger("director.warudo")
URL = os.getenv("WARUDO_API_URL", "ws://[::1]:19053/")
_TOKEN = re.compile(r"[0-9A-Fa-f]{32}")


class WarudoError(RuntimeError):
    pass


def token() -> str | None:
    """El token vigente de Warudo, o None si no está abierto."""
    if os.getenv("WARUDO_API_TOKEN"):
        return os.environ["WARUDO_API_TOKEN"]
    try:
        ps = subprocess.run(["pgrep", "-af", "warudo-client-electron"], capture_output=True, text=True).stdout
        m = re.search(r"--token=([0-9A-Fa-f]{32})", ps)
        if m:
            return m.group(1)
    except OSError:
        pass
    logs = glob.glob(os.path.expanduser("~/.local/share/Steam/steamapps/compatdata/*/pfx/drive_c/users/steamuser/"
                                        "AppData/LocalLow/HakuyaLabs/Warudo/Player.log"))
    for path in sorted(logs, key=os.path.getmtime, reverse=True):
        try:
            with open(path, errors="ignore") as f:
                found = re.findall(r"One Time API Auth Token:\s*([0-9A-Fa-f]{32})", f.read())
        except OSError:
            continue
        if found:
            return found[-1]
    return None


class Warudo:
    def __init__(self, url: str = URL, timeout: float = 20.0):
        self.url, self.timeout = url, timeout
        self.ws = None
        self._id = 0
        self._lock = asyncio.Lock()
        self._espera: tuple[str, asyncio.Future] | None = None
        self._lector: asyncio.Task | None = None

    @property
    def conectado(self) -> bool:
        return self.ws is not None and self._lector is not None and not self._lector.done()

    async def conectar(self) -> None:
        if self.conectado:
            return
        tok = token()
        if not tok:
            raise WarudoError("no encuentro el token de Warudo (¿está abierto?)")
        self.ws = await connect(self.url, subprotocols=[tok], open_timeout=10, max_size=16 * 2 ** 20)
        await self.ws.send(json.dumps({"action": "onConnected"}))
        self._lector = asyncio.create_task(self._leer())

    async def cerrar(self) -> None:
        if self._lector:
            self._lector.cancel()
        if self.ws:
            await self.ws.close()
        self.ws = self._lector = None

    async def _leer(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                accion = m.get("action") if isinstance(m, dict) else None
                if self._espera and accion == self._espera[0] and m.get("isResponse") is not False \
                        and ("data" in m or "error" in m):
                    fut = self._espera[1]
                    if not fut.done():
                        fut.set_result(m)
        except Exception as e:  # noqa: BLE001  (se cayó la conexión: la próxima llamada reconecta)
            log.warning("conexión con Warudo cortada: %s", e)
        finally:
            if self._espera and not self._espera[1].done():
                self._espera[1].set_exception(WarudoError("se cortó la conexión con Warudo"))

    async def llamar(self, action: str, **data):
        """Una acción nativa; devuelve `data` o levanta WarudoError con el error de Warudo."""
        async with self._lock:
            await self.conectar()
            self._id += 1
            fut = asyncio.get_running_loop().create_future()
            objetivo = data.get("graph") if action == "exportGraph" else data.get("asset") if action == "exportAsset" else None
            esperada = f"{action}:{str(objetivo).lower()}" if objetivo else action  # las exportaciones llevan el id
            self._espera = (esperada, fut)
            try:
                await self.ws.send(json.dumps({"action": action, "data": {"id": self._id, **data}}))
                m = await asyncio.wait_for(fut, self.timeout)
            except asyncio.TimeoutError:
                await self.cerrar()
                raise WarudoError(f"Warudo no respondió a {action}") from None
            finally:
                self._espera = None
        if m.get("error"):
            raise WarudoError(str(m["error"])[:300])
        return m.get("data")

    # --- atajos (las mismas acciones verificadas del MCP) ---
    async def puerto(self, entidad: str, puerto: str):
        return await self.llamar("getEntityDataInputPortValue", id=entidad, port=puerto)

    async def poner(self, entidad: str, puerto: str, valor) -> None:
        """valor: str, bool, número, dict ({"id","name"} para un asset) o None; viaja serializado a JSON, igual que
        hace el MCP con sus prefijos string:/bool:/json:."""
        await self.llamar("setEntityDataInputPortValue", id=entidad, port=puerto, value=json.dumps(valor, ensure_ascii=False),
                          broadcast=True)

    async def disparar(self, entidad: str, puerto: str) -> None:
        await self.llamar("invokeEntityTriggerPort", id=entidad, port=puerto)

    async def grafo(self, grafo: str, activo: bool) -> None:
        await self.llamar("setGraphEnabled", graph=grafo, enabled=activo)
