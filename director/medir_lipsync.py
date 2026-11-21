"""Mide el desfase boca ↔ audio de punta a punta, sin Warudo.

  .venv/bin/python -m director.medir_lipsync [--wav frase.wav] [--adelanto-ms 40]

Levanta joy_vmc (VMC a un puerto de prueba), reproduce ráfagas de tono (o un wav) con el Reproductor del director por el
sink "dolls", graba el monitor de ese sink (lo que capta OBS) y escucha el VMC. Compara, ráfaga por ráfaga, cuándo
SUENA y cuándo se ABRE la boca (suma de visemas A/I/U/E/O). Positivo = la boca va tarde.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import threading
import time
import wave

import numpy as np
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

from .audio import Reproductor
from .clientes import Cuerpo

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VMC_PUERTO, WS_PUERTO, SR = 39655, 8779, 24000


def rafagas(n=8, on=0.18, off=0.42) -> np.ndarray:
    t = np.arange(int(SR * on)) / SR
    tono = (0.5 * np.sin(2 * np.pi * 220 * t) * np.hanning(len(t)) ** 0.1).astype(np.float32)
    silencio = np.zeros(int(SR * off), np.float32)
    return np.concatenate([silencio] + [np.concatenate([tono, silencio]) for _ in range(n)])


def leer_wav(path) -> np.ndarray:
    with wave.open(path) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        sr = w.getframerate()
    return np.interp(np.linspace(0, len(x) - 1, int(len(x) * SR / sr)), np.arange(len(x)), x).astype(np.float32)


def flancos(ts, vals, umbral, min_sep=0.25):
    """Instantes en que la señal cruza el umbral hacia arriba (interpolado)."""
    out = []
    for i in range(1, len(vals)):
        if vals[i - 1] < umbral <= vals[i] and (not out or ts[i] - out[-1] > min_sep):
            f = (umbral - vals[i - 1]) / max(vals[i] - vals[i - 1], 1e-9)
            out.append(ts[i - 1] + f * (ts[i] - ts[i - 1]))
    return out


async def medir(args):
    # 1) VMC: suma de visemas con reloj monotónico
    boca: list[tuple[float, float]] = []
    vis = {}

    def val(_, name, v):
        if name in "AIUEO" and len(name) == 1:
            vis[name] = v

    def apply(*_):
        boca.append((time.monotonic(), sum(vis.values())))
    d = Dispatcher()
    d.map("/VMC/Ext/Blend/Val", val)
    d.map("/VMC/Ext/Blend/Apply", apply)
    osc = ThreadingOSCUDPServer(("127.0.0.1", VMC_PUERTO), d)
    threading.Thread(target=osc.serve_forever, daemon=True).start()
    jv = subprocess.Popen([sys.executable, "joy_vmc.py", "--personaje", "base", "--puerto", str(VMC_PUERTO),
                           "--ws-puerto", str(WS_PUERTO)], cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 2) grabación del monitor del sink con la marca de tiempo del ADC
    import sounddevice as sd
    grab: list[tuple[float, np.ndarray]] = []
    os.environ["PULSE_SOURCE"] = f"{args.sink}.monitor"

    def cb(indata, frames, ti, status):
        # instante (monotónico) de la primera muestra del bloque = ahora − (currentTime − inputBufferAdcTime)
        grab.append((time.monotonic() - (ti.currentTime - ti.inputBufferAdcTime), indata[:, 0].copy()))
    ent = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=240, device="pulse", callback=cb)
    try:
        await asyncio.sleep(1.5)
        cuerpo = Cuerpo(f"ws://127.0.0.1:{WS_PUERTO}")
        r = await cuerpo.enviar({"cmd": "estado"})
        if not r.get("ok"):
            sys.exit(f"joy_vmc no respondió: {r}")
        ent.start()
        repro = Reproductor(sink=args.sink, adelanto_ms=args.adelanto_ms)
        repro.iniciar()
        await asyncio.sleep(0.5)
        audio = leer_wav(args.wav) if args.wav else rafagas()
        await repro.decir(audio, SR, al_bloque=lambda t, v: cuerpo.rms(0.01 + v * 0.19))
        await asyncio.sleep(0.6)
        lat_salida = repro.latencia
        repro.cerrar()
    finally:
        ent.stop()
        jv.terminate()
        osc.shutdown()
    # 3) envolventes y flancos
    ta = np.concatenate([t0 + np.arange(len(b)) / SR for t0, b in grab])
    xa = np.abs(np.concatenate([b for _, b in grab]))
    k = int(SR * 0.005)
    env = np.convolve(xa, np.ones(k) / k, "same")
    fa = flancos(ta, env, 0.3 * env.max())
    tb = np.array([t for t, _ in boca])
    vb = np.array([v for _, v in boca])
    fb = flancos(tb, vb, 0.3 * max(vb.max(), 1e-6))
    pares = [min(fb, key=lambda b: abs(b - a)) - a for a in fa if fb]
    pares = [p for p in pares if abs(p) < 0.25]
    print(f"latencia de salida informada por PortAudio: {lat_salida * 1000:.0f} ms · adelanto: {args.adelanto_ms} ms")
    print(f"ráfagas en el audio: {len(fa)}, aperturas de boca: {len(fb)}, pares: {len(pares)}")
    if pares:
        ms = np.array(pares) * 1000
        print(f"desfase boca − audio: mediana {np.median(ms):+.0f} ms · min {ms.min():+.0f} · max {ms.max():+.0f}"
              f"  (positivo = la boca va tarde)")
        return float(np.median(ms))
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav")
    ap.add_argument("--adelanto-ms", type=int, default=40)
    ap.add_argument("--sink", default="dolls")
    asyncio.run(medir(ap.parse_args()))


if __name__ == "__main__":
    main()
