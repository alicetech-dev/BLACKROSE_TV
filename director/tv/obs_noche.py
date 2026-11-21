#!/usr/bin/env python3
"""OBS del canal nocturno (obs-websocket :4455): crea/actualiza
  · fuente «Cartelera (noche)» (:8822/cartelera/) ENCIMA de todo en JOY DISCORD y en TV NOCHE
  · escena «TV NOCHE»: pantalla del canal (:8822/tv/, opaca, con audio) + Joy y Kuroki a los costados (misma disposición que MEDIO TIEMPO)
    + subtítulos + voz de las dolls + música de Chrome + logo/marquesina de BlackRose TV + cartelera.
Es idempotente. Uso: python3 obs_noche.py [crear|refrescar]"""
import asyncio, base64, hashlib, json, os, sys
import aiohttp

CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
ESC, REF = "TV NOCHE", "MEDIO TIEMPO"
CART, PANT = "Cartelera (noche)", "TV Noche (pantalla)"
CART_TV = "Cartelera (TV noche)"   # la de la escena TV NOCHE: ?cada=0 (no tapa el video; la tarjeta sale al empezar cada programa)
U_CART, U_PANT, U_CART_TV = "http://127.0.0.1:8822/cartelera/", "http://127.0.0.1:8822/tv/", "http://127.0.0.1:8822/cartelera/?cada=0"


async def main(accion):
    pw = json.load(open(CFG))["server_password"]
    async with aiohttp.ClientSession() as s, s.ws_connect("ws://127.0.0.1:4455") as ws:
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
                    return m["d"]

        ok = lambda r: r["requestStatus"]["result"]
        entradas = {i["inputName"] for i in (await req("GetInputList"))["responseData"]["inputs"]}
        escenas = [e["sceneName"] for e in (await req("GetSceneList"))["responseData"]["scenes"]]

        def ajustes(url, audio):
            return {"url": url, "width": 1920, "height": 1080, "fps_custom": True, "fps": 30, "reroute_audio": audio, "css": "", "shutdown": False}

        # 1) fuentes nuevas (se crean dentro de una escena; la primera vez en JOY DISCORD → cartelera / TV NOCHE → pantalla)
        if ESC not in escenas:
            print("crear escena", ESC, ok(await req("CreateScene", {"sceneName": ESC})))
        if PANT not in entradas:
            print("crear", PANT, ok(await req("CreateInput", {"sceneName": ESC, "inputName": PANT, "inputKind": "browser_source", "sceneItemEnabled": True, "inputSettings": ajustes(U_PANT, True)})))
        else:
            await req("SetInputSettings", {"inputName": PANT, "inputSettings": ajustes(U_PANT, True), "overlay": True})
        if CART_TV not in entradas:
            print("crear", CART_TV, ok(await req("CreateInput", {"sceneName": ESC, "inputName": CART_TV, "inputKind": "browser_source", "sceneItemEnabled": True, "inputSettings": ajustes(U_CART_TV, False)})))
        else:
            await req("SetInputSettings", {"inputName": CART_TV, "inputSettings": ajustes(U_CART_TV, False), "overlay": True})
        if CART not in entradas:
            print("crear", CART, ok(await req("CreateInput", {"sceneName": "JOY DISCORD", "inputName": CART, "inputKind": "browser_source", "sceneItemEnabled": True, "inputSettings": ajustes(U_CART, False)})))
        else:
            await req("SetInputSettings", {"inputName": CART, "inputSettings": ajustes(U_CART, False), "overlay": True})

        async def items(esc):
            return (await req("GetSceneItemList", {"sceneName": esc}))["responseData"]["sceneItems"]

        # 2) escena TV NOCHE: de abajo hacia arriba
        ref = {i["sourceName"]: i for i in await items(REF)}
        ya = {i["sourceName"] for i in await items(ESC)}
        orden = [PANT, "Joy (overlay)", "Kuroki v2", "Joy subtitulos", "Voz Joy (dolls)", "Captura de salida de audio (PulseAudio)", "BlackRose TV (logo)", CART_TV]
        for n in orden:
            if n in ya:
                continue
            r = await req("CreateSceneItem", {"sceneName": ESC, "sourceName": n, "sceneItemEnabled": True})
            sid = r.get("responseData", {}).get("sceneItemId")
            print("  +", n, ok(r))
            if sid and n in ("Joy (overlay)", "Kuroki v2") and n in ref:
                t = ref[n]["sceneItemTransform"]
                await req("SetSceneItemTransform", {"sceneName": ESC, "sceneItemId": sid, "sceneItemTransform": {k: t[k] for k in ("positionX", "positionY", "scaleX", "scaleY")}})
            if sid and n in ("Joy subtitulos", "BlackRose TV (logo)", CART_TV):
                await req("SetSceneItemTransform", {"sceneName": ESC, "sceneItemId": sid, "sceneItemTransform": {"positionX": 0, "positionY": 0}})
        # 3) la cartelera, la última (arriba de todo) en las dos escenas
        its = await items(ESC)       # la cartelera «normal» ya no va en TV NOCHE (taparía el video cada 10 min)
        for i in its:
            if i["sourceName"] == CART:
                await req("RemoveSceneItem", {"sceneName": ESC, "sceneItemId": i["sceneItemId"]})
        for esc, nom in (("JOY DISCORD", CART), (ESC, CART_TV)):
            its = await items(esc)
            c = next((i for i in its if i["sourceName"] == nom), None)
            if c:
                await req("SetSceneItemIndex", {"sceneName": esc, "sceneItemId": c["sceneItemId"], "sceneItemIndex": len(its) - 1})
        if accion == "refrescar":
            for n in (PANT, CART, CART_TV):
                await req("PressInputPropertiesButton", {"inputName": n, "propertyName": "refreshnocache"})
        for esc in ("JOY DISCORD", ESC):
            print("--", esc)
            for i in (await items(esc))[-8:]:
                print(f"   {i['sceneItemIndex']:2} {i['sourceName']} {'on' if i['sceneItemEnabled'] else 'OFF'}")


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "crear"))
