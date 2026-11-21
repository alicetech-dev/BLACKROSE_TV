"""Reproducción con lip-sync de verdad: el RMS que llega a joy_vmc es el del bloque que SUENA.

El callback de PortAudio escribe bloques de ~20 ms; para cada uno calcula su RMS y el instante en que va a salir por
el DAC (outputBufferDacTime − currentTime, la latencia que informa el propio stream). El lado asyncio manda
{"rms": x} a joy_vmc justo en ese instante, menos `adelanto` (la boca de joy_vmc tiene un ataque suavizado de ~40 ms,
así que se le avisa un poco antes). Cada frase empieza en un bloque nuevo, así el bloque i ↔ la envolvente i.

Salida: el sink de PipeWire `sink` (un null-sink "dolls" que OBS captura y un loopback lo manda a tus auriculares;
ver audio_setup.sh). Sin sink: la salida por defecto.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import os
import threading
import time

import numpy as np

log = logging.getLogger("director.audio")


def envolvente(x: np.ndarray, n: int) -> np.ndarray:
    """RMS por bloque de n muestras, normalizado 0..1 por frase (piso = percentil 20, techo = percentil 95)."""
    bloques = max(1, int(np.ceil(len(x) / n)))
    pad = np.zeros(bloques * n, np.float32)
    pad[:len(x)] = x
    rms = np.sqrt((pad.reshape(bloques, n) ** 2).mean(1) + 1e-12)
    piso, pico = np.percentile(rms, 20), np.percentile(rms, 95)
    return np.clip((rms - piso * 1.2) / max(pico - piso * 1.2, 1e-6), 0, 1).astype(np.float32)


def remuestrear(x: np.ndarray, sr: int, sr_out: int) -> np.ndarray:
    if sr == sr_out:
        return x.astype(np.float32)
    n = int(round(len(x) * sr_out / sr))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


class _Item:
    def __init__(self, audio, env, fut, al_empezar, al_bloque):
        self.audio, self.env, self.fut, self.al_empezar, self.al_bloque = audio, env, fut, al_empezar, al_bloque
        self.pos, self.bloque = 0, 0


class Reproductor:
    def __init__(self, sr: int = 24000, bloque_ms: int = 20, sink: str | None = None, adelanto_ms: int = 40,
                 volumen: float = 1.0):
        self.sr, self.n = sr, int(sr * bloque_ms / 1000)
        self.sink, self.adelanto, self.volumen = sink, adelanto_ms / 1000, volumen
        self.cola: collections.deque[_Item] = collections.deque()
        self.actual: _Item | None = None
        self.lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stream = None
        self.latencia = 0.0  # última latencia de salida medida (s)

    def iniciar(self) -> None:
        import sounddevice as sd
        self.loop = asyncio.get_running_loop()
        device = None
        if self.sink:
            os.environ["PULSE_SINK"] = self.sink  # el plugin ALSA "pulse" lo respeta al abrir el stream
            device = "pulse"
        self.stream = sd.OutputStream(samplerate=self.sr, channels=1, dtype="float32", blocksize=self.n,
                                      latency="low", device=device, callback=self._cb)
        self.stream.start()
        log.info("audio: %s @ %d Hz, bloque %d ms, latencia informada %.0f ms", self.sink or "salida por defecto",
                 self.sr, self.n * 1000 // self.sr, self.stream.latency * 1000)

    def cerrar(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream.close()

    # --- hilo de audio -------------------------------------------------------
    def _cb(self, out, frames, time_info, status):
        ahora = time.monotonic()
        demora = max(0.0, time_info.outputBufferDacTime - time_info.currentTime)
        self.latencia = demora
        cuando = ahora + demora
        out.fill(0)
        with self.lock:
            it = self.actual
            if it is None and self.cola:
                it = self.actual = self.cola.popleft()
            if it is None:
                return
            trozo = it.audio[it.pos:it.pos + frames]
            out[:len(trozo), 0] = trozo * self.volumen
            if it.pos == 0:
                self._post(it.al_empezar, cuando)
            env = float(it.env[it.bloque]) if it.bloque < len(it.env) else 0.0
            self._post(it.al_bloque, cuando, env)
            it.pos += frames
            it.bloque += 1
            if it.pos >= len(it.audio):
                self.actual = None
                fin = cuando + len(trozo) / self.sr
                self.loop.call_soon_threadsafe(self._terminar, it.fut, fin)

    def _post(self, fn, cuando, *args):
        if fn:
            self.loop.call_soon_threadsafe(self._agendar, fn, cuando, args)

    # --- lado asyncio -------------------------------------------------------
    def _agendar(self, fn, cuando, args):
        self.loop.call_at(cuando - self.adelanto, fn, cuando, *args)

    def _terminar(self, fut, fin):
        if not fut.done():
            self.loop.call_at(fin, lambda: fut.done() or fut.set_result(fin))

    async def decir(self, audio: np.ndarray, sr: int, al_empezar=None, al_bloque=None) -> float:
        """Encola una frase y espera a que termine de sonar. al_empezar(t) / al_bloque(t, env 0..1) se llaman en el
        instante (reloj de asyncio) en que ese audio sale por el DAC, menos `adelanto`. Devuelve el instante del fin."""
        x = remuestrear(audio, sr, self.sr)
        fut = self.loop.create_future()
        with self.lock:
            self.cola.append(_Item(x, envolvente(x, self.n), fut, al_empezar, al_bloque))
        return await fut

    def callar(self) -> None:
        """Corta lo que suena y lo encolado (pop/stop, o cuando la interrumpen)."""
        with self.lock:
            items = ([self.actual] if self.actual else []) + list(self.cola)
            self.actual = None
            self.cola.clear()
        for it in items:
            if not it.fut.done():
                it.fut.set_result(time.monotonic())
