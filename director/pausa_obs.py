#!/usr/bin/env python3
"""PAUSA COMERCIAL de BlackRose TV en OBS (obs-websocket :4455, clave del flatpak).

  ~/joy_vmc/pausa.sh on [minutos]   pasa a la escena PAUSA COMERCIAL (con «volvemos en MM:SS» si das minutos) y recuerda la escena actual
  ~/joy_vmc/pausa.sh off            vuelve a la escena de antes
  ~/joy_vmc/pausa.sh crear          crea la escena (y la fuente) si no existen; no cambia de escena
Los spots no usan IA en vivo: cero tokens. Spots y textos: director/web/pausa/generar.py.
"""
import asyncio, base64, hashlib, json, os, sys
import aiohttp

CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
ESCENA, FUENTE, URL = "PAUSA COMERCIAL", "Pausa comercial (spots)", "http://127.0.0.1:8822/pausa/"
RECUERDO = os.path.expanduser("~/joy_vmc/logs/pausa_escena_anterior.txt")


async def main(accion: str, minutos: float):
    pw = json.load(open(CFG))["server_password"]
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("ws://127.0.0.1:4455") as ws:
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
                while True:   # los eventos de OBS se cuelan entre medio: solo me sirve la respuesta (op 7)
                    m = json.loads((await ws.receive()).data)
                    if m["op"] == 7 and m["d"].get("requestId") == "x":
                        return m["d"]

            escenas = [e["sceneName"] for e in (await req("GetSceneList"))["responseData"]["scenes"]]
            if ESCENA not in escenas:
                await req("CreateScene", {"sceneName": ESCENA})
                r = await req("CreateInput", {"sceneName": ESCENA, "inputName": FUENTE, "inputKind": "browser_source", "sceneItemEnabled": True,
                    "inputSettings": {"url": URL, "width": 1920, "height": 1080, "fps_custom": True, "fps": 30, "reroute_audio": True, "css": "", "shutdown": False}})
                print("escena creada:", ESCENA, "| fuente:", r["requestStatus"]["result"])
            # autorreparación: si la fuente de los spots falta o está desactivada dentro de la escena, la pausa sale en NEGRO (pasó el 19-nov)
            its = (await req("GetSceneItemList", {"sceneName": ESCENA}))["responseData"]["sceneItems"]
            it = next((i for i in its if i["sourceName"] == FUENTE), None)
            if it is None:
                await req("CreateSceneItem", {"sceneName": ESCENA, "sourceName": FUENTE, "sceneItemEnabled": True}); print("reparado: la fuente no estaba en la escena")
            elif not it["sceneItemEnabled"]:
                await req("SetSceneItemEnabled", {"sceneName": ESCENA, "sceneItemId": it["sceneItemId"], "sceneItemEnabled": True}); print("reparado: la fuente estaba desactivada")
            if accion == "crear":
                return
            actual = (await req("GetCurrentProgramScene"))["responseData"]["currentProgramSceneName"]
            if accion == "on":
                if actual != ESCENA:
                    open(RECUERDO, "w").write(actual)
                async with s.post("http://127.0.0.1:8822/api/pausa", json={"minutos": minutos} if minutos else {"accion": "off"}) as r:
                    await r.read()
                await req("SetInputMute", {"inputName": FUENTE, "inputMuted": False})
                await req("SetCurrentProgramScene", {"sceneName": ESCENA})
                print("PAUSA al aire" + (f" ({minutos:g} min)" if minutos else "") + f" · escena anterior: {actual}")
            else:
                vuelta = open(RECUERDO).read().strip() if os.path.exists(RECUERDO) else "JOY DISCORD"
                async with s.post("http://127.0.0.1:8822/api/pausa", json={"accion": "off"}) as r:
                    await r.read()
                await req("SetCurrentProgramScene", {"sceneName": vuelta if vuelta in escenas else escenas[0]})
                await req("SetInputMute", {"inputName": FUENTE, "inputMuted": True})   # que la música de la pausa no se cuele en las otras escenas
                print("de vuelta en:", vuelta)


if __name__ == "__main__":
    acc = sys.argv[1] if len(sys.argv) > 1 else "crear"
    if acc not in ("on", "off", "crear"):
        sys.exit(__doc__)
    asyncio.run(main(acc, float(sys.argv[2]) if len(sys.argv) > 2 else 0))
