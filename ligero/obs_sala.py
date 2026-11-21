#!/usr/bin/env python3
"""OBS: escena «SALA DE CONTROL» (obs-websocket :4455). Idempotente; NO cambia la escena en vivo.
  · fuente «Sala 3D (WebGL)»: http://127.0.0.1:8830/ (ligero/sala.py: Joy y Kuroki dentro de la pieza hacker o del cuarto de Joy)
    - shutdown=True: cuando la escena no está al aire OBS descarga la página (libera RAM y GPU)
  · encima: subtítulos, voz de las dolls, audio, logo del canal, traductor JA→ES y cartelera (los mismos que usa TV NOCHE)
  · Joy y Kuroki NO van como overlays aparte: ya están dentro del 3D
  python3 ligero/obs_sala.py [crear]"""
import asyncio, base64, hashlib, json, os, sys
import aiohttp

CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
ESC, FUENTE, REF = "SALA DE CONTROL", "Sala 3D (WebGL)", "TV NOCHE"
ENCIMA = ["Joy subtitulos", "Voz Joy (dolls)", "Captura de salida de audio (PulseAudio)", "BlackRose TV (logo)", "Traductor (JA→ES)", "Cartelera (TV noche)"]
AJ = {"url": "http://127.0.0.1:8830/", "width": 1920, "height": 1080, "fps_custom": True, "fps": 30, "reroute_audio": False, "css": "", "shutdown": True}


async def main():
    pw = json.load(open(CFG))["server_password"]
    async with aiohttp.ClientSession() as s, s.ws_connect("ws://127.0.0.1:4455") as ws:
        h = json.loads((await ws.receive()).data)
        ident = {"op": 1, "d": {"rpcVersion": 1}}
        a = h["d"].get("authentication")
        if a:
            sec = base64.b64encode(hashlib.sha256((pw + a["salt"]).encode()).digest()).decode()
            ident["d"]["authentication"] = base64.b64encode(hashlib.sha256((sec + a["challenge"]).encode()).digest()).decode()
        await ws.send_json(ident); await ws.receive()

        async def req(t, d=None):
            await ws.send_json({"op": 6, "d": {"requestType": t, "requestId": "x", "requestData": d or {}}})
            while True:
                m = json.loads((await ws.receive()).data)
                if m["op"] == 7 and m["d"].get("requestId") == "x":
                    return m["d"]
        ok = lambda r: r["requestStatus"]["result"]
        ent = {i["inputName"] for i in (await req("GetInputList"))["responseData"]["inputs"]}
        esc = [e["sceneName"] for e in (await req("GetSceneList"))["responseData"]["scenes"]]
        items = lambda e: req("GetSceneItemList", {"sceneName": e})

        if ESC not in esc:
            print("crear escena", ESC, ok(await req("CreateScene", {"sceneName": ESC})))
        if FUENTE not in ent:
            print("crear", FUENTE, ok(await req("CreateInput", {"sceneName": ESC, "inputName": FUENTE, "inputKind": "browser_source", "sceneItemEnabled": True, "inputSettings": AJ})))
        else:
            await req("SetInputSettings", {"inputName": FUENTE, "inputSettings": AJ, "overlay": True})
        ya = {i["sourceName"]: i for i in (await items(ESC))["responseData"]["sceneItems"]}
        if FUENTE not in ya:
            print("  +", FUENTE, ok(await req("CreateSceneItem", {"sceneName": ESC, "sourceName": FUENTE, "sceneItemEnabled": True})))
            ya = {i["sourceName"]: i for i in (await items(ESC))["responseData"]["sceneItems"]}
        await req("SetSceneItemIndex", {"sceneName": ESC, "sceneItemId": ya[FUENTE]["sceneItemId"], "sceneItemIndex": 0})   # la sala, al fondo
        for n in ENCIMA:
            if n in ya:
                continue
            if n not in ent:
                print("  (no existe la fuente", n, "— se omite)"); continue
            r = await req("CreateSceneItem", {"sceneName": ESC, "sourceName": n, "sceneItemEnabled": True})
            sid = r.get("responseData", {}).get("sceneItemId"); print("  +", ESC, "←", n, ok(r))
            if sid and n in ("Joy subtitulos", "BlackRose TV (logo)", "Traductor (JA→ES)", "Cartelera (TV noche)"):
                await req("SetSceneItemTransform", {"sceneName": ESC, "sceneItemId": sid, "sceneItemTransform": {"positionX": 0, "positionY": 0}})
        print("--", ESC, [f"{i['sceneItemIndex']}:{i['sourceName']}" for i in (await items(ESC))["responseData"]["sceneItems"]])
        print("escena al aire ahora:", (await req("GetCurrentProgramScene"))["responseData"]["currentProgramSceneName"], "(no se tocó)")

asyncio.run(main())
