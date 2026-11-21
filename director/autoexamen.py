"""AUTO-EXAMEN de BlackRose TV: mira lo que ve el espectador (no solo si los procesos están vivos) y repara lo que pueda.
La ORQUESTA lo corre cada ~5 min (`python -m director.autoexamen`); también a mano. Resultado: logs/autoexamen.json y logs/autoexamen.log.
  1. OBS: ninguna escena de la TV puede estar «vacía» (todas sus fuentes desactivadas = pantalla NEGRA): se reactivan sus fuentes.
     La escena AL AIRE además debe tener fuentes activas; si no, se vuelve a TV NOCHE. OBS debe estar transmitiendo.
  2. Páginas que alimentan las escenas responden (pausa comercial + spots, sala 3D, overlay del canal, capa Japón) y su servicio se reinicia si no.
  3. La pausa comercial tiene material (spots.json con ≥ 20 spots) y la sala de control tiene stock de cortes (apoyo.json fresco; si no, lo produce).
  4. Un 4B/9B responde (cerebro :8087); si no, se avisa en el reporte (la orquesta ya lo levanta).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import subprocess
import time

import aiohttp

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(RAIZ, "logs")
CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
ESCENAS_TV = ["TV NOCHE", "ESTUDIO 2049", "PAUSA COMERCIAL", "SALA DE CONTROL", "JAPON", "SHOW KUROKI", "MEDIO TIEMPO", "JOY DISCORD", "FAST PENGUIN"]
PAGINAS = [("http://127.0.0.1:8822/pausa/spots.json", "brtv-overlay"), ("http://127.0.0.1:8830/api/sala", "sala3d"), ("http://127.0.0.1:8826/api/japon", "japon-capa"),
           ("http://127.0.0.1:8822/api/tv", "brtv-overlay"), ("http://127.0.0.1:8087/health", None)]
log = logging.getLogger("autoexamen")


async def get(url: str, t: float = 4) -> tuple[int, bytes]:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=t)) as s, s.get(url) as r:
            return r.status, await r.read()
    except Exception:  # noqa: BLE001
        return 0, b""


async def obs() -> list[str]:
    arreglos: list[str] = []
    pw = json.load(open(CFG))["server_password"]
    async with aiohttp.ClientSession() as s, s.ws_connect("ws://127.0.0.1:4455", timeout=5) as ws:
        h = json.loads((await ws.receive()).data)
        ident = {"op": 1, "d": {"rpcVersion": 1}}
        a = h["d"].get("authentication")
        if a:
            sec = base64.b64encode(hashlib.sha256((pw + a["salt"]).encode()).digest()).decode()
            ident["d"]["authentication"] = base64.b64encode(hashlib.sha256((sec + a["challenge"]).encode()).digest()).decode()
        await ws.send_json(ident)
        await ws.receive()

        async def req(t, d=None):
            await ws.send_json({"op": 6, "d": {"requestType": t, "requestId": "x", "requestData": d or {}}})
            while True:
                m = json.loads((await ws.receive()).data)
                if m["op"] == 7 and m["d"].get("requestId") == "x":
                    return m["d"].get("responseData") or {}

        existentes = [e["sceneName"] for e in (await req("GetSceneList"))["scenes"]]
        vacias = []
        for esc in ESCENAS_TV:
            if esc not in existentes:
                continue
            its = (await req("GetSceneItemList", {"sceneName": esc}))["sceneItems"]
            if its and not any(i["sceneItemEnabled"] for i in its):
                vacias.append(esc)
                for i in its:
                    await req("SetSceneItemEnabled", {"sceneName": esc, "sceneItemId": i["sceneItemId"], "sceneItemEnabled": True})
                arreglos.append(f"escena «{esc}» estaba vacía (negro): reactivé {len(its)} fuentes")
        # Joy y Kuroki solo pueden estar ocultas durante un video/música (el director las oculta y las reactiva); si no, se reactivan
        try:
            item = json.load(open(os.path.join(RAIZ, "director", "tv", "estado.json"))).get("item", "")
        except (OSError, ValueError):
            item = ""
        if not item.startswith(("video:", "musica:")):
            for esc in ("JOY DISCORD",):      # TV NOCHE (20-nov): solo medios a pantalla grande, sin rostros (la charla va al ESTUDIO 2049)
                if esc in existentes:
                    for i in (await req("GetSceneItemList", {"sceneName": esc}))["sceneItems"]:
                        if i["sourceName"] in ("Joy (overlay)", "Kuroki v2") and not i["sceneItemEnabled"]:
                            await req("SetSceneItemEnabled", {"sceneName": esc, "sceneItemId": i["sceneItemId"], "sceneItemEnabled": True})
                            arreglos.append(f"«{i['sourceName']}» estaba oculta en {esc} fuera de un video: reactivada")
        aire = (await req("GetCurrentProgramScene"))["currentProgramSceneName"]
        its = (await req("GetSceneItemList", {"sceneName": aire}))["sceneItems"]
        if aire in ESCENAS_TV and not any(i["sceneItemEnabled"] for i in its):
            await req("SetCurrentProgramScene", {"sceneName": "TV NOCHE"})
            arreglos.append(f"al aire había «{aire}» sin fuentes: volví a TV NOCHE")
        if not (await req("GetStreamStatus")).get("outputActive"):
            await req("StartStream")
            arreglos.append("OBS no estaba transmitiendo: StartStream")
    return arreglos


async def examen() -> dict:
    r: dict = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "arreglos": [], "problemas": []}
    try:
        r["arreglos"] += await asyncio.wait_for(obs(), 30)
    except Exception as e:  # noqa: BLE001
        r["problemas"].append(f"OBS no responde ({e!s:.60})")
    for url, svc in PAGINAS:
        cod, _ = await get(url)
        if cod != 200:
            r["problemas"].append(f"{url} → {cod}")
            if svc:
                subprocess.run(["systemctl", "--user", "restart", svc], capture_output=True, timeout=30)
                r["arreglos"].append(f"reinicié {svc}")
    try:
        n = len(json.load(open(os.path.join(RAIZ, "director", "web", "pausa", "spots.json"))))
        if n < 20:
            r["problemas"].append(f"la pausa comercial tiene solo {n} spots")
            subprocess.run([os.path.join(RAIZ, ".venv/bin/python"), os.path.join(RAIZ, "director/web/pausa/generar.py"), "voz"], capture_output=True, timeout=300, cwd=RAIZ)
            r["arreglos"].append("regeneré los spots de la pausa")
    except Exception as e:  # noqa: BLE001
        r["problemas"].append(f"spots.json ilegible: {e!s:.60}")
    try:
        from director.tv import apoyo
        d = await apoyo.asegurar()
        r["apoyo"] = {"cortes": len(d.get("paquetes", [])), "edad_min": round((time.time() - d.get("hecho", 0)) / 60)}
        if not d.get("paquetes"):
            r["problemas"].append("sin stock de cortes de la sala de control")
    except Exception as e:  # noqa: BLE001
        r["problemas"].append(f"apoyo: {e!s:.80}")
    os.makedirs(LOGS, exist_ok=True)
    json.dump(r, open(os.path.join(LOGS, "autoexamen.json"), "w"), ensure_ascii=False, indent=1)
    if r["arreglos"] or r["problemas"]:
        open(os.path.join(LOGS, "autoexamen.log"), "a").write(json.dumps(r, ensure_ascii=False) + "\n")
    return r


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asyncio.run(examen()), ensure_ascii=False, indent=1))
