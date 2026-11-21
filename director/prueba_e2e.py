"""Prueba de punta a punta de la fase 2 (sin Warudo): texto → agente → XTTS → audio + lip-sync + emoción.

Requiere corriendo: el agente (`serve`, :8790) y un joy_vmc por doll mandando VMC a los puertos de --vmc
(p. ej. `joy_vmc.py --personaje joy --ws-puerto 8770 --puerto 39655`). Escucha ese VMC y reporta por turno:
tiempos (reacción, primer token, primer audio), si la boca se mueve SOLO mientras suena, y qué expresiones y gestos
se vieron.

  .venv/bin/python -m director.prueba_e2e --vmc joy=39655,bambi=39656
"""
from __future__ import annotations

import argparse
import asyncio
import threading
import time

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

from . import __main__ as D

EXPR = ("Joy", "Fun", "Angry", "Sorrow", "Surprised", "Smug", "Sparkle", "Kyu", "Wink_L", "Wink_R", "Fang",
        "happy", "angry", "sad", "relaxed", "surprised")
MENSAJES = [
    ("joy", "Joy! te extrañé muchísimo, ¿qué hiciste hoy?"),
    ("bambi", "Bambi, tell me something that made you giggle today"),
    ("joy", "wow, no te puedo creer jajaja"),
]


class Oreja:
    """Escucha el VMC de una doll: por cuadro, apertura de boca (A+I+U+E+O) y expresiones."""

    def __init__(self, puerto: int):
        self.cuadros: list[tuple[float, float, dict]] = []
        self.vals: dict[str, float] = {}
        d = Dispatcher()
        d.map("/VMC/Ext/Blend/Val", lambda _, n, v: self.vals.__setitem__(n, v))
        d.map("/VMC/Ext/Blend/Apply", lambda *_: self.cuadros.append(
            (time.monotonic(), sum(self.vals.get(v, 0.0) for v in "AIUEO"),
             {k: v for k, v in self.vals.items() if k in EXPR and v > 0.15})))
        self.srv = ThreadingOSCUDPServer(("127.0.0.1", puerto), d)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def ventana(self, t0, t1):
        return [c for c in self.cuadros if t0 <= c[0] <= t1]


async def main_async(args):
    cfg = D.cargar()
    orejas = {k: Oreja(int(p)) for k, p in (x.split("=") for x in args.vmc.split(","))}
    sonando: dict[str, list[list[float]]] = {d: [] for d in orejas}
    gestos: dict[str, list[str]] = {d: [] for d in orejas}

    def emitir(ev):
        D.imprimir(ev)
        if ev["type"] == "estado" and ev["estado"].get("gesto"):
            g = ev["estado"]["gesto"]
            if not gestos[ev["doll"]] or gestos[ev["doll"]][-1] != g:
                gestos[ev["doll"]].append(g)

    dolls = await D.armar(cfg, list(orejas), emitir=emitir)
    for did, r in dolls.items():  # registrar cuándo suena cada frase (instante real de DAC)
        orig = r.repro.decir

        async def decir(audio, sr, al_empezar=None, al_bloque=None, _o=orig, _d=did):
            ini = {}

            def emp(t, *a):
                ini["t"] = t + r.repro.adelanto
                if al_empezar:
                    al_empezar(t, *a)
            fin = await _o(audio, sr, al_empezar=emp, al_bloque=al_bloque)
            if "t" in ini:
                sonando[_d].append([ini["t"], fin])
            return fin
        r.repro.decir = decir
    await asyncio.sleep(1.0)
    for did, texto in MENSAJES:
        print(f"\n>>> {did}: {texto}")
        t0 = time.monotonic()
        n0 = len(sonando[did])
        gestos[did].clear()
        await dolls[did].turno(texto, cfg["usuario"])
        await asyncio.sleep(0.8)
        t1 = time.monotonic()
        cuadros = orejas[did].ventana(t0, t1)
        tramos = sonando[did][n0:]
        dentro = [b for (t, b, _) in cuadros if any(a <= t <= z for a, z in tramos)]
        fuera = [b for (t, b, _) in cuadros if not any(a - 0.1 <= t <= z + 0.25 for a, z in tramos)]
        expr: dict[str, float] = {}
        for _, _, e in cuadros:
            for k, v in e.items():
                expr[k] = max(expr.get(k, 0), v)
        abierta = lambda xs: sum(1 for b in xs if b > 0.1) / max(len(xs), 1)  # noqa: E731
        print(f"    boca abierta mientras suena: {abierta(dentro):.0%} de {len(dentro)} cuadros · "
              f"en silencio: {abierta(fuera):.0%} de {len(fuera)} cuadros")
        print(f"    expresiones vistas (máx): {', '.join(f'{k} {v:.2f}' for k, v in sorted(expr.items(), key=lambda x: -x[1]))}")
        print(f"    gestos: {' → '.join(gestos[did])}  · voz: {dolls[did].estado.voz}")
    for r in dolls.values():
        r.repro.cerrar()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vmc", default="joy=39655,bambi=39656")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
