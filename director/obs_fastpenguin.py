#!/usr/bin/env python3
"""OBS: escena «FAST PENGUIN» (obs-websocket :4455), la que usa la TV para pasarle el aire a Alice a la hora de Fast Penguin. Idempotente.
De abajo hacia arriba:
  · fondo espacial (por si el juego aún no está abierto) y el JUEGO: captura PipeWire «FP Juego (captura)» (este OBS no trae xcomposite; la primera vez hay que elegir la ventana del juego en el selector del portal)
  · audio: «Captura de salida de audio (PulseAudio)» (el sonido del juego) + «Mic Blackrose (ardilla)» (voz_ardilla, ya existente)
  · puntajes y nivel: «FP Rango (YDPYAU)» (código de party, rango, puntos, medallas), «FP Escalera (nivel)» (pirámide de rangos, barra a LEYENDA); el rango ya trae jugadora, grupo y medallas
  · chat: cinta superior (fp_chat_cinta) + caja del chat de Twitch; marquesina abajo
Los datos salen de ~/overlays_fastpenguin (serve.py :8806, estado.json). NO cambia la escena al aire.
  .venv/bin/python director/obs_fastpenguin.py [crear]"""
import asyncio, base64, hashlib, json, os
import aiohttp

CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
ESC = "FAST PENGUIN"
FP = "http://127.0.0.1:8806/"
NAV = {"width": 1920, "height": 1080, "fps": 30, "shutdown": False, "restart_when_active": False}
# (nombre, tipo, ajustes) de abajo hacia arriba; los que ya existen en la colección se reutilizan tal cual
CAPAS = [
    ("FP Fondo espacio", "browser_source", {**NAV, "url": FP + "fp_espacio.html?v=11"}),
    ("FP Juego (captura)", "pipewire-screen-capture-source", {"ShowCursor": False}),
    ("Captura de salida de audio (PulseAudio)", None, None),
    ("Mic Blackrose (ardilla)", None, None),
    ("FP Escalera (nivel)", "browser_source", {**NAV, "url": FP + "fp_escalera.html?x=20&y=70&s=0.8&v=9"}),
    ("FP Rango (YDPYAU)", None, None),
    ("FP Chat (Twitch)", "browser_source", {**NAV, "url": "file:///home/alice/overlays_nocturno/noche_chat.html?x=20&y=760&w=520&h=250&show=1&twitch=barbieblackrose&fondo=galaga&v=9"}),
    ("FP Chat Cinta", "browser_source", {**NAV, "url": FP + "fp_chat_cinta.html?v=9"}),
    ("FP Marquesina", "browser_source", {**NAV, "url": FP + "fp_marquesina.html?v=9acc&t=1"}),
]


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
        if ESC not in [e["sceneName"] for e in (await req("GetSceneList"))["responseData"]["scenes"]]:
            print("crear escena", ESC, ok(await req("CreateScene", {"sceneName": ESC})))
        ya = {i["sourceName"]: i for i in (await req("GetSceneItemList", {"sceneName": ESC}))["responseData"]["sceneItems"]}
        for n, tipo, aj in CAPAS:
            if n not in ent:
                if not tipo:
                    print("  (no existe", n, "— se omite)"); continue
                print("  crear", n, ok(await req("CreateInput", {"sceneName": ESC, "inputName": n, "inputKind": tipo, "sceneItemEnabled": True, "inputSettings": aj})))
                ent.add(n)
            elif tipo == "browser_source":
                await req("SetInputSettings", {"inputName": n, "inputSettings": aj, "overlay": True})
            ya = {i["sourceName"]: i for i in (await req("GetSceneItemList", {"sceneName": ESC}))["responseData"]["sceneItems"]}
            if n not in ya:
                print("  +", n, ok(await req("CreateSceneItem", {"sceneName": ESC, "sourceName": n, "sceneItemEnabled": True})))
                ya = {i["sourceName"]: i for i in (await req("GetSceneItemList", {"sceneName": ESC}))["responseData"]["sceneItems"]}
            it = ya[n]["sceneItemId"]
            await req("SetSceneItemEnabled", {"sceneName": ESC, "sceneItemId": it, "sceneItemEnabled": True})
        # orden (el primero queda al fondo) y el juego ajustado a 1920×1080
        for k, (n, _, _) in enumerate(CAPAS):
            if n in ya:
                await req("SetSceneItemIndex", {"sceneName": ESC, "sceneItemId": ya[n]["sceneItemId"], "sceneItemIndex": k})
        if "FP Juego (captura)" in ya:
            await req("SetSceneItemTransform", {"sceneName": ESC, "sceneItemId": ya["FP Juego (captura)"]["sceneItemId"], "sceneItemTransform": {
                "positionX": 0, "positionY": 0, "alignment": 5, "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsAlignment": 0, "boundsWidth": 1920, "boundsHeight": 1080}})
        for n in ("Mic Blackrose (ardilla)", "Captura de salida de audio (PulseAudio)"):
            if n in ent:
                await req("SetInputMute", {"inputName": n, "inputMuted": False})
        print("--", ESC, [f"{i['sceneItemIndex']}:{i['sourceName']}" for i in (await req("GetSceneItemList", {"sceneName": ESC}))["responseData"]["sceneItems"]])
        print("escena al aire ahora:", (await req("GetCurrentProgramScene"))["responseData"]["currentProgramSceneName"], "(no se tocó)")

asyncio.run(main())
