"""OBS · capa homogénea de BlackRose TV (2026-11-20). Idempotente: se puede correr las veces que sea.

  .venv/bin/python -m director.obs_capa

- «Capa BlackRose (estudio)»  → :8822/capa/            en ESTUDIO 2049 (UNA sola instancia con la cama musical; audio a OBS)
- «Capa BlackRose (sin audio)» → :8822/capa/?cama=0&sin=vis   en TV NOCHE y SALA DE CONTROL (zócalo, cinta, invitación)
- TV NOCHE ordenada: la pantalla a lienzo completo (0,0, escala 1) y sin la miniatura de la sala 3D encima.
- «BlackRose TV (logo)» y «Cartelera (TV noche)» arriba, sin recorte, en las escenas de la TV (estaban corridos abajo).
No cambia la escena al aire.
"""
from __future__ import annotations

import asyncio

from .mediotiempo import OBS

URL = "http://127.0.0.1:8822/capa/"
CAPAS = {"Capa BlackRose (estudio)": (URL, True), "Capa BlackRose (sin audio)": (URL + "?cama=0&sin=vis", False), "Capa BlackRose (tv)": (URL + "?cama=0&sin=vis,zoc", False)}
ESCENAS = {"ESTUDIO 2049": "Capa BlackRose (estudio)", "TV NOCHE": "Capa BlackRose (tv)", "SALA DE CONTROL": "Capa BlackRose (sin audio)"}
ARRIBA_DE = ("Estudio BRTV (Unity)", "TV Noche (pantalla)", "Sala 3D (WebGL)")   # la capa va justo encima del fondo de cada escena
CERO = {"positionX": 0, "positionY": 0, "scaleX": 1.0, "scaleY": 1.0, "cropTop": 0, "cropBottom": 0, "cropLeft": 0, "cropRight": 0, "rotation": 0}


async def main() -> None:
    o = OBS()
    if not await o.conectar():
        raise SystemExit("OBS sin websocket")
    entradas = {i["inputName"] for i in (await o.pedir("GetInputList"))["inputs"]}
    escenas = {e["sceneName"] for e in (await o.pedir("GetSceneList"))["scenes"]}
    for esc, capa in ESCENAS.items():
        if esc not in escenas:
            continue
        items = (await o.pedir("GetSceneItemList", {"sceneName": esc}))["sceneItems"]
        url, audio = CAPAS[capa]
        conf = {"url": url, "width": 1920, "height": 1080, "fps": 30, "fps_custom": True, "reroute_audio": audio, "shutdown": False, "restart_when_active": False}
        if capa not in entradas:
            r = await o.pedir("CreateInput", {"sceneName": esc, "inputName": capa, "inputKind": "browser_source", "inputSettings": conf, "sceneItemEnabled": True})
            entradas.add(capa)
            iid = r["sceneItemId"]
        else:
            await o.pedir("SetInputSettings", {"inputName": capa, "inputSettings": conf})
            ya = next((i for i in items if i["sourceName"] == capa), None)
            iid = ya["sceneItemId"] if ya else (await o.pedir("CreateSceneItem", {"sceneName": esc, "sourceName": capa, "sceneItemEnabled": True}))["sceneItemId"]
        await o.pedir("SetSceneItemTransform", {"sceneName": esc, "sceneItemId": iid, "sceneItemTransform": CERO})
        await o.pedir("SetSceneItemEnabled", {"sceneName": esc, "sceneItemId": iid, "sceneItemEnabled": True})
        items = (await o.pedir("GetSceneItemList", {"sceneName": esc}))["sceneItems"]
        fondo = next((i for i in items if i["sourceName"] in ARRIBA_DE), None)
        if fondo:
            await o.pedir("SetSceneItemIndex", {"sceneName": esc, "sceneItemId": iid, "sceneItemIndex": fondo["sceneItemIndex"] + 1})
        if audio:
            await o.pedir("SetInputVolume", {"inputName": capa, "inputVolumeDb": -6.0})
        for i in items:
            if i["sourceName"] in ("BlackRose TV (logo)", "Cartelera (TV noche)") or (esc == "TV NOCHE" and i["sourceName"] == "TV Noche (pantalla)"):
                await o.pedir("SetSceneItemTransform", {"sceneName": esc, "sceneItemId": i["sceneItemId"], "sceneItemTransform": CERO})
            if esc == "TV NOCHE" and i["sourceName"] == "Sala 3D (WebGL)":
                await o.pedir("SetSceneItemEnabled", {"sceneName": esc, "sceneItemId": i["sceneItemId"], "sceneItemEnabled": False})
        for i in items:      # otra capa vieja en la escena → fuera
            if i["sourceName"].startswith("Capa BlackRose") and i["sourceName"] != capa:
                await o.pedir("RemoveSceneItem", {"sceneName": esc, "sceneItemId": i["sceneItemId"]})
        print("ok", esc, "←", capa)
    await o.cerrar()


if __name__ == "__main__":
    asyncio.run(main())
