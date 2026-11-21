"""Caché de voz: todo lo que se sintetiza queda guardado con su texto para reciclarlo.

~/joy_vmc/cache_voz/<perfil>/<h[:2]>/<h>.mp3 + .json  ({texto, voz, palabras:[[palabra, ini_s, fin_s], ...]})
<perfil> = voz + velocidad + altura (Kuroki y Joy no se mezclan aunque usen la misma voz de edge).
  · frase repetida (normalizada: minúsculas, sin signos)  → se reusa el mp3, cero red.
  · sin red / edge caído → se arma la frase PEGANDO palabras ya grabadas (índice palabras.json por perfil),
    si están todas; si falta alguna, el motor decide (se calla o usa otra voz).
Las cuñas, cierres, saludos y respuestas del diccionario de decisiones se repiten mucho: casi siempre salen de aquí.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import unicodedata

import numpy as np

RAIZ = os.path.expanduser(os.environ.get("CACHE_VOZ", "~/joy_vmc/cache_voz"))
_lock = threading.Lock()


def norm(texto: str) -> str:
    t = unicodedata.normalize("NFKC", texto).lower()
    t = re.sub(r"[^\w\s぀-ヿ一-鿿]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def perfil(voz: str, velocidad: str, altura: str) -> str:
    return re.sub(r"[^\w+-]", "_", f"{voz}_{velocidad}_{altura}")


class Cache:
    def __init__(self, voz: str, velocidad: str = "+0%", altura: str = "+0Hz"):
        self.dir = os.path.join(RAIZ, perfil(voz, velocidad, altura))
        os.makedirs(self.dir, exist_ok=True)
        self.f_idx = os.path.join(self.dir, "palabras.json")
        try:
            self.idx: dict[str, list] = json.load(open(self.f_idx, encoding="utf-8"))
        except (OSError, ValueError):
            self.idx = {}
        self.voz = voz

    def _ruta(self, texto: str) -> str:
        h = hashlib.sha1(norm(texto).encode()).hexdigest()
        d = os.path.join(self.dir, h[:2])
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, h)

    def leer(self, texto: str) -> bytes | None:
        p = self._ruta(texto) + ".mp3"
        try:
            with open(p, "rb") as f:
                return f.read()
        except OSError:
            return None

    def guardar(self, texto: str, mp3: bytes, palabras: list[list]) -> None:
        base = self._ruta(texto)
        try:
            with open(base + ".mp3.tmp", "wb") as f:
                f.write(mp3)
            os.replace(base + ".mp3.tmp", base + ".mp3")
            json.dump({"texto": texto, "voz": self.voz, "palabras": palabras}, open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False)
        except OSError:
            return
        nuevas = False
        with _lock:
            for w, a, z in palabras:
                k = norm(w)
                if k and k not in self.idx and z - a > 0.05:
                    self.idx[k] = [os.path.relpath(base + ".mp3", self.dir), round(a, 3), round(z, 3)]
                    nuevas = True
            if nuevas:
                try:
                    json.dump(self.idx, open(self.f_idx + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
                    os.replace(self.f_idx + ".tmp", self.f_idx)
                except OSError:
                    pass

    def faltan(self, texto: str) -> list[str]:
        return [w for w in norm(texto).split() if w not in self.idx]

    def pegar(self, texto: str, sr: int) -> np.ndarray | None:
        """Frase armada con palabras grabadas antes (mono float32 a `sr`). None si falta alguna palabra."""
        ws = norm(texto).split()
        if not ws or any(w not in self.idx for w in ws):
            return None
        trozos, pausa = [], np.zeros(int(sr * 0.06), np.float32)
        pcm_de: dict[str, np.ndarray] = {}
        for w in ws:
            arch, a, z = self.idx[w]
            if arch not in pcm_de:
                pcm_de[arch] = decodificar(open(os.path.join(self.dir, arch), "rb").read(), sr)
            x = pcm_de[arch][int(a * sr): int(z * sr) + int(0.03 * sr)]
            if len(x) > 64:   # fundido corto en las puntas: sin clics al pegar
                n = min(len(x) // 4, int(0.012 * sr))
                x = x.copy(); x[:n] *= np.linspace(0, 1, n); x[-n:] *= np.linspace(1, 0, n)
            trozos += [x, pausa]
        return np.concatenate(trozos) if trozos else None

    def stats(self) -> dict:
        n = sum(len(fs) for _, _, fs in os.walk(self.dir)) // 2
        return {"perfil": os.path.basename(self.dir), "frases": n, "palabras": len(self.idx)}


def decodificar(mp3: bytes, sr: int) -> np.ndarray:
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(sr), "pipe:1"],
                         input=mp3, capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.float32).copy()
