#!/usr/bin/env python3
"""OBS: fuente «Alice duerme (insignia)» (http://127.0.0.1:8830/insignia, transparente, solo se ve mientras duerme) encima de las escenas de la TV. Idempotente."""
import asyncio, base64, hashlib, json, os
import aiohttp
CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
FUENTE = "Alice duerme (insignia)"
ESCENAS = ["TV NOCHE", "JOY DISCORD", "JAPON", "SHOW KUROKI", "MEDIO TIEMPO"]
AJ = {"url": "http://127.0.0.1:8830/insignia", "width": 1920, "height": 1080, "fps_custom": True, "fps": 15, "reroute_audio": False, "css": "", "shutdown": False}
async def main():
    pw = json.load(open(CFG))["server_password"]
    async with aiohttp.ClientSession() as s, s.ws_connect("ws://127.0.0.1:4455") as ws:
        h = json.loads((await ws.receive()).data); a = h["d"].get("authentication"); ident = {"op": 1, "d": {"rpcVersion": 1}}
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
        esc = [e["sceneName"] for e in (await req("GetSceneList"))["responseData"]["scenes"]]
        ent = {i["inputName"] for i in (await req("GetInputList"))["responseData"]["inputs"]}
        if FUENTE not in ent:
            primera = next(e for e in ESCENAS if e in esc)
            print("crear", (await req("CreateInput", {"sceneName": primera, "inputName": FUENTE, "inputKind": "browser_source", "sceneItemEnabled": True, "inputSettings": AJ}))["requestStatus"]["result"])
        else:
            await req("SetInputSettings", {"inputName": FUENTE, "inputSettings": AJ, "overlay": True})
        for e in ESCENAS:
            if e not in esc: continue
            its = (await req("GetSceneItemList", {"sceneName": e}))["responseData"]["sceneItems"]
            it = next((i for i in its if i["sourceName"] == FUENTE), None)
            if it is None:
                r = await req("CreateSceneItem", {"sceneName": e, "sourceName": FUENTE, "sceneItemEnabled": True}); sid = r["responseData"]["sceneItemId"]; print(" +", e)
            else:
                sid = it["sceneItemId"]
            await req("SetSceneItemEnabled", {"sceneName": e, "sceneItemId": sid, "sceneItemEnabled": True})
            n = len((await req("GetSceneItemList", {"sceneName": e}))["responseData"]["sceneItems"])
            await req("SetSceneItemIndex", {"sceneName": e, "sceneItemId": sid, "sceneItemIndex": n - 1})
asyncio.run(main())
