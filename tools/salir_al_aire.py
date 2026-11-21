"""Salida al aire de BlackRose TV: carta de ajuste (barras + cuenta) → voz en off → arranca el canal (tv-noche + orquesta).
Uso: .venv/bin/python tools/salir_al_aire.py [--en SEG]   (log: logs/salir_al_aire.log)
Requiere: OBS con la colección «Joy Discord» (escena AJUSTE), relé en :1935, cerebro :8087, overlay :8822."""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obsws import conectar
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AJ = os.path.join(RAIZ, "director", "web", "ajuste")
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
def http(u, t=4):
    try: return urllib.request.urlopen(u, timeout=t).status
    except Exception as e: return getattr(e, "code", 0)
async def main():
    espera = int(sys.argv[sys.argv.index("--en") + 1]) if "--en" in sys.argv else 20
    g = json.load(open(os.path.join(AJ, "guion.json"))); total = g["total"]
    for u in ("http://127.0.0.1:8822/ajuste/", "http://127.0.0.1:8087/health"):
        assert http(u) == 200, f"no responde {u}"
    assert os.path.exists(os.path.join(RAIZ, "logs", "envivo")) is False, "logs/envivo existe (modo en vivo de Alice)"
    async with conectar() as req:
        col = (await req("GetSceneCollectionList"))["currentSceneCollectionName"]; assert col == "Joy Discord", f"colección actual: {col}"
        assert not (await req("GetStreamStatus"))["outputActive"], "OBS ya está transmitiendo"
        t0 = time.time() + espera
        await req("SetInputSettings", {"inputName": "Carta de ajuste (web)", "inputSettings": {"url": f"http://127.0.0.1:8822/ajuste/?t0={int(t0*1000)}"}, "overlay": True})
        await req("PressInputPropertiesButton", {"inputName": "Carta de ajuste (web)", "propertyName": "refreshnocache"})
        await req("SetCurrentProgramScene", {"sceneName": "AJUSTE"})
        log("escena AJUSTE al programa; cuenta empieza a las", time.strftime("%H:%M:%S", time.localtime(t0)))
        await req("StartStream"); log("StartStream enviado")
        for _ in range(30):
            if (await req("GetStreamStatus"))["outputActive"]: break
            await asyncio.sleep(1)
        log("OBS transmitiendo:", (await req("GetStreamStatus"))["outputActive"])
    await asyncio.sleep(max(0, t0 - time.time()))
    p = subprocess.Popen(["paplay", os.path.join(AJ, "audio.wav")]); log("audio de ajuste + voz en off: inicio")
    await asyncio.sleep(total + 0.5)
    log("voz en off terminada; arranca el canal")
    est = os.path.join(RAIZ, "director", "tv", "estado.json")
    if os.path.exists(est): shutil.copy(est, est + ".bak-20261120-aire"); os.remove(est)
    subprocess.run(["systemctl", "--user", "start", "tv-noche", "brtv-orquesta"], check=False)
    log("tv-noche y brtv-orquesta iniciados")
asyncio.run(main())
