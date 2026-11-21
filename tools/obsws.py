"""Cliente mínimo de obs-websocket (:4455) con la clave de OBS Flatpak. Uso: async with conectar() as req: await req("GetVersion")"""
import aiohttp, base64, hashlib, json, os
from contextlib import asynccontextmanager
CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
@asynccontextmanager
async def conectar():
    pw = json.load(open(CFG))["server_password"]
    async with aiohttp.ClientSession() as s, s.ws_connect("ws://127.0.0.1:4455", timeout=5, max_msg_size=0) as ws:
        h = json.loads((await ws.receive()).data); ident = {"op": 1, "d": {"rpcVersion": 1}}
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
                    r = m["d"]; 
                    if not r["requestStatus"]["result"]: raise RuntimeError(f'{t}: {r["requestStatus"]}')
                    return r.get("responseData") or {}
        yield req
