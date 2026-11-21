#!/usr/bin/env python3
"""OBS de la Hora de Japón (obs-websocket :4455). Idempotente.
  · fuentes: «Japón (fondo)» (Fuji + láminas, opaca), «Japón (sakura)» (pétalos + hashtags), «Traductor (JA→ES)» (traducción al español + comentarios del chat traducidos)
  · escena «JAPON»: fondo + Joy y Kuroki a los costados + subtítulos + voz + música de Chrome + logo + sakura + traductor + cartelera
  · el traductor también va encima de JOY DISCORD y de TV NOCHE (traduce lo que digan en japonés y los comentarios del chat en cualquier momento)
  python3 obs_japon.py [crear|traductor]   («traductor» = solo añadirlo a JOY DISCORD / TV NOCHE)"""
import asyncio, base64, hashlib, json, os, sys
import aiohttp

CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
BASE = "http://127.0.0.1:8826/japon/"
FONDO, SAKURA, TRAD = "Japón (fondo)", "Japón (sakura)", "Traductor (JA→ES)"
ESC, REF = "JAPON", "TV NOCHE"


async def main(accion):
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

        def aj(capa):
            return {"url": f"{BASE}?capa={capa}", "width": 1920, "height": 1080, "fps_custom": True, "fps": 30, "reroute_audio": False, "css": "", "shutdown": False}

        async def items(e):
            return (await req("GetSceneItemList", {"sceneName": e}))["responseData"]["sceneItems"]

        async def entrada(nombre, capa, escena):
            if nombre not in ent:
                print("crear", nombre, ok(await req("CreateInput", {"sceneName": escena, "inputName": nombre, "inputKind": "browser_source", "sceneItemEnabled": True, "inputSettings": aj(capa)})))
                ent.add(nombre)
            else:
                await req("SetInputSettings", {"inputName": nombre, "inputSettings": aj(capa), "overlay": True})

        async def poner_arriba(escena, nombre, debajo_de=None):
            its = await items(escena)
            if not any(i["sourceName"] == nombre for i in its):
                print("  +", escena, "←", nombre, ok(await req("CreateSceneItem", {"sceneName": escena, "sourceName": nombre, "sceneItemEnabled": True})))
                its = await items(escena)
            it = next(i for i in its if i["sourceName"] == nombre)
            await req("SetSceneItemTransform", {"sceneName": escena, "sceneItemId": it["sceneItemId"], "sceneItemTransform": {"positionX": 0, "positionY": 0}})
            tope = len(its) - 1
            if debajo_de:
                d = next((i for i in its if i["sourceName"] == debajo_de), None)
                tope = max(0, d["sceneItemIndex"] - 1) if d else tope
            await req("SetSceneItemIndex", {"sceneName": escena, "sceneItemId": it["sceneItemId"], "sceneItemIndex": tope})

        if accion == "crear":
            if ESC not in esc:
                print("crear escena", ESC, ok(await req("CreateScene", {"sceneName": ESC})))
            await entrada(FONDO, "fondo", ESC)
            await entrada(SAKURA, "sakura", ESC)
            await entrada(TRAD, "trad", ESC)
            ref = {i["sourceName"]: i for i in await items(REF)}
            ya = {i["sourceName"] for i in await items(ESC)}
            for n in [FONDO, "Joy (overlay)", "Kuroki v2", "Joy subtitulos", "Voz Joy (dolls)", "Captura de salida de audio (PulseAudio)", "BlackRose TV (logo)", SAKURA, TRAD, "Cartelera (TV noche)"]:
                if n in ya:
                    continue
                r = await req("CreateSceneItem", {"sceneName": ESC, "sourceName": n, "sceneItemEnabled": True})
                sid = r.get("responseData", {}).get("sceneItemId"); print("  +", ESC, "←", n, ok(r))
                if sid and n in ("Joy (overlay)", "Kuroki v2") and n in ref:
                    t = ref[n]["sceneItemTransform"]
                    await req("SetSceneItemTransform", {"sceneName": ESC, "sceneItemId": sid, "sceneItemTransform": {k: t[k] for k in ("positionX", "positionY", "scaleX", "scaleY")}})
                if sid and n in (FONDO, "Joy subtitulos", "BlackRose TV (logo)", SAKURA, TRAD, "Cartelera (TV noche)"):
                    await req("SetSceneItemTransform", {"sceneName": ESC, "sceneItemId": sid, "sceneItemTransform": {"positionX": 0, "positionY": 0}})
        else:
            await entrada(TRAD, "trad", "JOY DISCORD")
        # el traductor: activado ahora encima de JOY DISCORD (bajo la cartelera) y en TV NOCHE
        await poner_arriba("JOY DISCORD", TRAD, debajo_de="Cartelera (noche)")
        await poner_arriba("TV NOCHE", TRAD, debajo_de="Cartelera (TV noche)")
        for e in ("JOY DISCORD", "TV NOCHE", ESC):
            if e in esc or e == ESC:
                print("--", e, [f"{i['sceneItemIndex']}:{i['sourceName']}" for i in (await items(e))[-6:]])
asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "crear"))
