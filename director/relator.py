"""Relator de partidos: Joy (relatora) y Kuroki (comentarista) narran lo que juega Blackrose.

Cada ~15 s saca una captura de la fuente del juego en OBS, Grok (visión) la lee junto con lo último que se dijo y
devuelve el estado (marcador, minuto, evento) y una línea corta para cada doll. La línea se manda al director
(/api/relato): si alguien habla, se descarta (el relato viejo no sirve), salvo goles/penales, que van sí o sí.

  .venv/bin/python -m director.relator --local "Real Madrid" --rival "Barcelona"
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import random
import re
import time

import aiohttp
import websockets

from director.redaccion import XAI, MODELO, _clave

log = logging.getLogger("director.relator")
OBS_CFG = "/home/alice/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json"
DIRECTOR = "http://127.0.0.1:8780/api/relato"

PROMPT = """Eres el equipo de transmisión de BlackRose TV narrando EN VIVO un partido de PES 2011 que juega Blackrose
(la dueña del canal) con el {local} contra el {rival} (la computadora). Mira la captura del juego.
Lo que ya se dijo (NO lo repitas): {historia}
Estado anterior: {estado}
Responde SOLO este JSON:
{{"pantalla": "juego | repeticion | menu | entretiempo | final | carga",
 "marcador": "ej. RMA 1-0 BAR, leído del marcador en pantalla, o \\"\\" si no se ve",
 "minuto": "minuto si se ve, o \\"\\"",
 "evento": "gol_blackrose | gol_rival | penal | ocasion | atajada | falta | corner | tarjeta | saque | juego | nada",
 "detalle": "qué se ve, en 1 frase (zona de la cancha, quién tiene la pelota, jugador si se lee su nombre)",
 "joy": "línea de JOY, relatora apasionada estilo relato futbolero latino, hincha de Blackrose: máx. 18 palabras",
 "kuroki": "línea de KUROKI, comentarista analítica, irónica y seca, también hincha de Blackrose: máx. 18 palabras"}}
Reglas: español neutro; habla del juego que se VE, no inventes jugadas ni nombres que no se lean; si es un gol escribe
GOOOL largo; si el rival ataca, sufre; si es menú/carga, comenten la previa o pidan que arranque. Nada de emojis."""


class Obs:
    def __init__(self):
        self.ws = None

    async def pedir(self, tipo: str, datos: dict) -> dict:
        if self.ws is None:
            pw = json.load(open(OBS_CFG))["server_password"]
            self.ws = await websockets.connect("ws://127.0.0.1:4455", max_size=2 ** 26)
            h = json.loads(await self.ws.recv())["d"]
            ident = {"rpcVersion": 1}
            if "authentication" in h:
                a = h["authentication"]
                s = base64.b64encode(hashlib.sha256((pw + a["salt"]).encode()).digest()).decode()
                ident["authentication"] = base64.b64encode(hashlib.sha256((s + a["challenge"]).encode()).digest()).decode()
            await self.ws.send(json.dumps({"op": 1, "d": ident}))
            await self.ws.recv()
        rid = str(time.time())
        await self.ws.send(json.dumps({"op": 6, "d": {"requestType": tipo, "requestId": rid, "requestData": datos}}))
        while True:
            m = json.loads(await self.ws.recv())
            if m["op"] == 7 and m["d"]["requestId"] == rid:
                return m["d"]

    async def captura(self, fuente: str) -> str | None:
        try:
            d = await self.pedir("GetSourceScreenshot", {"sourceName": fuente, "imageFormat": "jpg", "imageWidth": 1024,
                                                         "imageCompressionQuality": 80})
            return (d.get("responseData") or {}).get("imageData")
        except Exception as e:  # noqa: BLE001  (OBS reiniciado: reconecta la próxima)
            log.warning("obs: %s", e)
            self.ws = None
            return None


async def grok(s: aiohttp.ClientSession, img: str, texto: str) -> dict | None:
    async with s.post(XAI, headers={"Authorization": f"Bearer {_clave()}"},
                      json={"model": MODELO, "max_tokens": 400, "temperature": 0.8,
                            "messages": [{"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": img}}, {"type": "text", "text": texto}]}]}) as r:
        d = await r.json(content_type=None)
    if "choices" not in d:
        log.warning("grok: %s", str(d)[:200])
        return None
    m = re.search(r"\{.*\}", d["choices"][0]["message"]["content"], re.S)
    return json.loads(m.group(0)) if m else None


async def decir(s: aiohttp.ClientSession, quien: str, texto: str, urgente: bool = False) -> bool:
    try:
        async with s.post(DIRECTOR, json={"quien": quien, "texto": texto, "urgente": urgente}) as r:
            return r.status == 200
    except aiohttp.ClientError:
        return False


async def main(a) -> None:
    obs, historia, estado = Obs(), [], {}
    turno, ult_habla = "joy", 0.0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as s:
        async with s.post(DIRECTOR, json={"accion": "on", "tema": f"Partido: {a.local} vs {a.rival}"}):
            pass
        try:
            while True:
                t0 = time.time()
                img = await obs.captura(a.fuente)
                if img:
                    try:
                        r = await grok(s, img, PROMPT.format(local=a.local, rival=a.rival,
                                                             historia=" | ".join(historia[-6:]) or "nada aún",
                                                             estado=json.dumps(estado, ensure_ascii=False) or "{}"))
                    except Exception as e:  # noqa: BLE001
                        log.warning("grok: %s", e)
                        r = None
                    if r:
                        ev, pant = r.get("evento", "nada"), r.get("pantalla", "")
                        log.info("%s %s %s · %s", pant, r.get("marcador"), r.get("minuto"), ev)
                        grande = ev in ("gol_blackrose", "gol_rival", "penal")
                        cambio = r.get("marcador") and r.get("marcador") != estado.get("marcador")
                        espera = a.cada if pant == "juego" else a.cada * 3   # en menús/repeticiones hablan menos
                        if grande or cambio or time.time() - ult_habla > espera or (ev in ("ocasion", "atajada") and random.random() < .7):
                            urg = bool(grande or cambio)
                            orden = ["joy", "kuroki"] if (grande or turno == "joy") else ["kuroki"]
                            dijo = False
                            for q in orden:
                                ok = bool(r.get(q)) and await decir(s, q, r[q], urg)
                                log.info("  %s %s: %s", "→" if ok else "✗", q, r.get(q))
                                if ok:
                                    historia.append(f"{q}: {r[q]}")
                                    dijo = True
                                    if not urg:
                                        break
                            if dijo:
                                ult_habla = time.time()
                                turno = "kuroki" if turno == "joy" else "joy"
                        estado = {k: r.get(k) for k in ("pantalla", "marcador", "minuto", "evento")}
                await asyncio.sleep(max(3.0, a.intervalo - (time.time() - t0)))
        finally:
            async with s.post(DIRECTOR, json={"accion": "off"}):
                pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fuente", default="Captura de pantalla (PipeWire) 5")
    p.add_argument("--local", default="Real Madrid")
    p.add_argument("--rival", default="Barcelona")
    p.add_argument("--intervalo", type=float, default=15)
    p.add_argument("--cada", type=float, default=25, help="segundos mínimos entre comentarios sin evento")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        pass
