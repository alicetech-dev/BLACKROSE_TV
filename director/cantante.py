"""Las dolls cantan la canción mientras bailan: boca al compás del audio y caras que cambian.

El Reproductor MMD de Warudo pisa el cuerpo pero no toca la cara, y nadie más se la mueve durante el baile. Acá:
  · se captura el audio que Warudo manda a la salida (el sink-input de Warudo.exe, o el monitor de la salida por
    defecto si no se encuentra) con `parec`, y de cada bloque de 20 ms se saca la energía de la banda de la voz
    (250–3500 Hz); normalizada con un techo/piso que se adaptan solos, va a joy_vmc como {"rms": x} (modo streaming),
    así la boca sigue la canción como si cantara;
  · cada pocos segundos se cambia la emoción (más alegre/vivaz cuando la canción sube, más suave cuando baja), con
    algún guiño y mirada a los costados, y cada doll con la suya. Al terminar la cara vuelve a neutral.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import subprocess

import numpy as np

log = logging.getLogger("director.cantante")

SR, BLOQUE = 16000, 320                      # 20 ms
FUERTES = ["alegre", "feliz", "emocionada", "picara", "presumida", "coqueta", "guiño", "gatuna"]
SUAVES = ["neutral", "picara", "feliz", "coqueta", "avergonzada", "presumida"]
MIRADAS = ["camara", "camara", "camara", "izquierda", "derecha", "arriba"]


def _entrada_warudo() -> list[str]:
    """Argumentos de parec para capturar lo que suena desde Warudo (o la salida por defecto)."""
    try:
        out = subprocess.run(["pactl", "--format=json", "list", "sink-inputs"], capture_output=True, text=True, timeout=3).stdout
        for si in json.loads(out or "[]"):
            p = si.get("properties") or {}
            if "warudo" in (p.get("application.name", "") + p.get("application.process.binary", "")).lower():
                return [f"--monitor-stream={si['index']}"]
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return ["-d", "@DEFAULT_MONITOR@"]


class Envolvente:
    """Energía de la banda de la voz por bloque, normalizada 0..1 con piso y techo adaptativos."""

    def __init__(self):
        self.win = np.hanning(BLOQUE).astype(np.float32)
        f = np.fft.rfftfreq(BLOQUE, 1 / SR)
        self.banda = (f >= 250) & (f <= 3500)
        self.media, self.pico, self.suave = 1e-4, 1e-3, 0.0

    def paso(self, x: np.ndarray) -> float:
        """En una mezcla completa la energía casi no baja de la media: la boca se abre según cuánto SOBRE la media de
        ~1 s está el bloque (sílabas y golpes) y se cierra en los valles; el pico adaptativo fija el 100 %."""
        e = float(np.sqrt((np.abs(np.fft.rfft(x * self.win))[self.banda] ** 2).mean())) / BLOQUE
        self.pico = max(e, self.pico * 0.9993)
        self.media += (e - self.media) * 0.03
        silencio = e < self.pico * 0.02
        v = 0.0 if silencio else float(np.clip(0.45 + 0.9 * (e - self.media) / max(self.pico - self.media, 1e-9), 0.0, 1.0))
        self.suave += (v - self.suave) * (0.7 if v > self.suave else 0.4)    # ataque rápido, soltada un poco más lenta
        return self.suave


class Cantante:
    def __init__(self, cuerpos: dict, rng: random.Random | None = None, rms_piso: float = 0.01, rms_techo: float = 0.20):
        """cuerpos: {doll: Cuerpo} de las que cantan (el lip-sync de joy_vmc espera el RMS crudo entre piso y techo)."""
        self.cuerpos, self.r = cuerpos, rng or random.Random()
        self.piso, self.techo = rms_piso, rms_techo
        self._tareas: list[asyncio.Task] = []
        self._proc: asyncio.subprocess.Process | None = None
        self.nivel = 0.0                                          # energía suavizada (lenta), la usan las caras

    def activa(self) -> bool:
        return bool(self._tareas)

    async def iniciar(self) -> None:
        await self.parar(restaurar=False)
        self._tareas = [asyncio.create_task(self._audio()), asyncio.create_task(self._caras())]

    async def parar(self, restaurar: bool = True) -> None:
        tareas, self._tareas = self._tareas, []
        for t in tareas:
            t.cancel()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        self._proc = None
        if tareas and restaurar:
            for c in self.cuerpos.values():
                await c.enviar({"rms": 0.0, "emocion": "neutral", "mirar": "camara"}, esperar=False)

    async def _abrir(self):
        """El sink-input de Warudo aparece cuando empieza la música: se reintenta unos segundos antes de rendirse."""
        for intento in range(8):
            args = _entrada_warudo()
            self._proc = await asyncio.create_subprocess_exec(
                "parec", *args, "--format=s16le", f"--rate={SR}", "--channels=1", "--latency-msec=20",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            if args[0] != "-d" or intento >= 5:        # encontró a Warudo (o ya no hay más que esperar)
                return self._proc
            await asyncio.sleep(0.5)
            self._proc.kill()
        return self._proc

    async def _audio(self) -> None:
        env, lento = Envolvente(), 0.0
        try:
            p = await self._abrir()
            while True:
                datos = await p.stdout.readexactly(BLOQUE * 2)
                x = np.frombuffer(datos, np.int16).astype(np.float32) / 32768.0
                v = env.paso(x)
                lento += (v - lento) * 0.004
                self.nivel = lento
                rms = self.piso + v * (self.techo - self.piso) if v > 0.03 else 0.0
                for c in self.cuerpos.values():
                    c.rms(rms)
        except (asyncio.IncompleteReadError, OSError):
            log.warning("se cortó la captura del audio; la boca queda quieta")
        except asyncio.CancelledError:
            pass

    async def _caras(self) -> None:
        validas = {}
        for d, c in self.cuerpos.items():
            info = await c.enviar({"cmd": "listar"})
            validas[d] = set(info.get("emociones") or [])
        ultima: dict[str, str] = {}
        try:
            while True:
                await asyncio.sleep(self.r.uniform(2.5, 6.0))
                fuerte = self.nivel > 0.12
                for d, c in self.cuerpos.items():
                    pool = [e for e in (FUERTES if fuerte else SUAVES) if e in validas.get(d, ()) and e != ultima.get(d)]
                    if not pool:
                        continue
                    e = self.r.choice(pool)
                    ultima[d] = e
                    await c.enviar({"emocion": e, "intensidad": round(self.r.uniform(0.6, 1.0), 2),
                                    "mirar": self.r.choice(MIRADAS)}, esperar=False)
                    await asyncio.sleep(self.r.uniform(0.2, 0.9))      # las dos no cambian de cara a la vez
        except asyncio.CancelledError:
            pass
