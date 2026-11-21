"""Voz de cada doll detrás de una interfaz: `xtts` (voz clonada, GPU vía el orquestador :9020) o `google` (gTTS, sin
clave ni VRAM). `ConRespaldo` usa XTTS y, si no está listo (arranque en frío ~30-40 s tras el apagado por inactividad)
o falla, habla con gTTS mientras tanto y despierta XTTS en segundo plano.

Todas devuelven audio float32 mono y su sample rate. El texto se limpia con clean_for_speech del agente.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import subprocess
import sys
import threading
import time
import wave
from types import SimpleNamespace

import httpx
import numpy as np

sys.path.insert(0, os.path.expanduser("~/proyectos/agente_unificado"))
from agente.tts import TTS, TTSError, clean_for_speech  # noqa: E402

log = logging.getLogger("director.voz")

_NO_LETRA = re.compile(r"[^\w\s']|_")


def solo_letras(texto: str) -> str:
    """Sin puntos, comas ni símbolos: XTTS los lee como artefactos en el audio. Quedan letras, números y el apóstrofo."""
    limpio = " ".join(_NO_LETRA.sub(" ", texto).split())
    return limpio or texto

_ES = re.compile(r"[ñáéíóú¿¡]|\b(que|qué|de|el|la|los|las|y|en|es|por|para|con|mi|tu|vos|sos|estoy|estás|hola|muy|pero|no|sí|me|te|lo|una?|como|cómo|bebé|amor)\b", re.I)
_EN = re.compile(r"\b(the|and|you|i|i'm|is|are|to|of|my|your|it|that|this|what|so|oh|baby|daddy|hi|hey|with|for|just|really|yes|love)\b", re.I)


_JA = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")


def idioma(texto: str, defecto: str = "en") -> str:
    """ja por kana/kanji; es/en por palabras frecuentes (la frase es corta; alcanza y no cuesta nada)."""
    if len(_JA.findall(texto)) >= max(2, len(texto.strip()) // 4):  # kana/kanji: japonés (XTTS «ja»)
        return "ja"
    es, en = len(_ES.findall(texto)), len(_EN.findall(texto))
    if es == en:
        return defecto
    return "es" if es > en else "en"


def cambiar_tono(x: np.ndarray, sr: int, factor: float, formantes: bool = True) -> np.ndarray:
    """Sube/baja el tono sin cambiar la velocidad (ffmpeg + rubberband). factor 1.05 = ~+1 semitono.
    formantes=False corre también los formantes: con factor < 1 la voz cambia de timbre (de mujer a hombre/robot)."""
    if abs(factor - 1.0) < 1e-3 or not len(x):
        return x
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "f32le", "-ac", "1", "-ar", str(sr), "-i", "pipe:0",
                        "-af", f"rubberband=pitch={factor:.4f}:formant={'preserved' if formantes else 'shifted'}", "-f", "f32le", "-ac", "1",
                        "-ar", str(sr), "pipe:1"], input=x.astype(np.float32).tobytes(), capture_output=True)
    if r.returncode:
        log.warning("no pude cambiar el tono: %s", r.stderr[-200:])
        return x
    return np.frombuffer(r.stdout, np.float32).copy()


def _wav_a_np(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, {2: np.int16, 4: np.int32}[sw]).astype(np.float32) / float(2 ** (8 * sw - 1))
    return x.reshape(-1, ch).mean(1), sr


class Voz:
    nombre = "voz"

    async def sintetizar(self, texto: str, lang: str) -> tuple[np.ndarray, int]:
        raise NotImplementedError


class MudoVoz(Voz):
    """Sin voz: no sintetiza nada (audio None → el director solo mueve el cuerpo). Para Joy solo-texto."""
    nombre = "mudo"

    async def sintetizar(self, texto, lang):
        return None, 0


class XTTSVoz(Voz):
    nombre = "xtts"

    def __init__(self, url: str, voice: str | None = None, speaker: str | None = None,
                 temperature: float | None = None, speed: float | None = None, tono: float = 1.0):
        self.url, self.voice, self.speaker = url, voice, speaker
        self.opciones = {"temperature": temperature, "speed": speed}
        self.tono = tono
        self.avisar = None
        self._visto_listo = 0.0
        self.cli = TTS(SimpleNamespace(tts_enabled=True, tts_url=url, tts_language="en"))
        self.directo = os.getenv("XTTS_DIRECTO", "http://127.0.0.1:8020")  # para ver si está arriba SIN despertarlo

    async def listo(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=1.5) as c:
                r = await c.get(self.directo + "/health")
                return r.status_code == 200 and r.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError):
            return False

    async def despertar(self) -> None:
        """Un GET al proxy del orquestador hace que levante XTTS (y reinicia su reloj de inactividad)."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5, read=180)) as c:
                await c.get(self.url.rsplit("/", 1)[0] + "/health")
        except httpx.HTTPError as e:
            log.info("despertar XTTS: %s", e)

    async def sintetizar(self, texto, lang):
        if self.avisar and time.monotonic() - self._visto_listo > 20 and not await self.listo():
            self.avisar("xtts_esperando")  # arranque en frío: el pedido espera a que el orquestador lo levante
        data = await self.cli.synthesize(solo_letras(texto), language=lang, voice=self.voice, speaker=self.speaker,
                                         options=self.opciones)
        self._visto_listo = time.monotonic()
        x, sr = _wav_a_np(data)
        if self.tono != 1.0:
            x = await asyncio.to_thread(cambiar_tono, x, sr, self.tono)
        return x, sr


class GoogleVoz(Voz):
    """gTTS: el TTS gratuito del traductor de Google (sin clave, sin SLA). Una voz por idioma; cada doll se distingue
    por el acento (tld) y un leve cambio de tono."""
    nombre = "google"

    def __init__(self, tld: dict[str, str] | None = None, tono: float = 1.0, sr: int = 24000, formantes: bool = True):
        self.tld, self.tono, self.sr, self.formantes = tld or {}, tono, sr, formantes

    def _sync(self, texto: str, lang: str) -> np.ndarray:
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(texto, lang=lang, tld=self.tld.get(lang, "com")).write_to_fp(buf)
        pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1",
                              "-ar", str(self.sr), "pipe:1"], input=buf.getvalue(), capture_output=True, check=True).stdout
        return cambiar_tono(np.frombuffer(pcm, np.float32).copy(), self.sr, self.tono, self.formantes)

    async def sintetizar(self, texto, lang):
        return await asyncio.to_thread(self._sync, texto, lang), self.sr


def _clave_grok() -> str:
    """GROK_API_KEY del entorno o, si no, de ~/.env (nunca se loguea)."""
    k = os.getenv("GROK_API_KEY", "")
    if not k:
        try:
            for ln in open(os.path.expanduser("~/.env"), encoding="utf-8"):
                if ln.startswith("GROK_API_KEY="):
                    k = ln.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
    return k


class GrokVoz(Voz):
    """TTS de xAI (Grok) en la nube: cero GPU/VRAM. Voces femeninas: ara, aurora, carina, celeste, eve, iris, liora,
    luna, ursa. Devuelve MP3 24 kHz; ffmpeg lo pasa a float32."""
    nombre = "grok"

    def __init__(self, voice: str = "eve", tono: float = 1.0, sr: int = 24000):
        self.voice, self.tono, self.sr = voice or "eve", tono, sr
        self.clave = _clave_grok()

    async def sintetizar(self, texto, lang):
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=40)) as c:
            r = await c.post("https://api.x.ai/v1/tts", headers={"Authorization": f"Bearer {self.clave}"},
                             json={"text": texto, "voice_id": self.voice, "language": lang})
        if r.status_code != 200:
            raise TTSError(f"grok tts {r.status_code}: {r.text[:160]}")
        mp3 = r.content

        def _dec() -> np.ndarray:
            pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1",
                                  "-ar", str(self.sr), "pipe:1"], input=mp3, capture_output=True, check=True).stdout
            x = np.frombuffer(pcm, np.float32).copy()
            return cambiar_tono(x, self.sr, self.tono) if self.tono != 1.0 else x
        return await asyncio.to_thread(_dec), self.sr


class PiperVoz(Voz):
    """Piper: TTS neural LOCAL por CPU (onnxruntime), sin red ni GPU. El último respaldo del «modo apocalipsis»:
    si edge no responde y la caché no tiene las palabras, la frase igual se dice. Solo español (no hay voz japonesa)."""
    nombre = "piper"
    MODELO = os.path.expanduser(os.environ.get("PIPER_VOZ", "~/joy_vmc/voces_piper/es_MX-claude-high.onnx"))
    _voz = None
    _lock = threading.Lock()

    def __init__(self, tono: float = 1.0, sr: int = 24000):
        self.tono, self.sr = tono, sr

    @classmethod
    def disponible(cls) -> bool:
        return os.path.exists(cls.MODELO)

    def _sync(self, texto: str) -> np.ndarray:
        from piper import PiperVoice
        with PiperVoz._lock:
            if PiperVoz._voz is None:
                PiperVoz._voz = PiperVoice.load(self.MODELO)
            trozos = list(PiperVoz._voz.synthesize(texto))
        if not trozos:
            raise TTSError("piper sin audio")
        x = np.concatenate([c.audio_float_array for c in trozos]).astype(np.float32)
        sr0 = trozos[0].sample_rate
        if sr0 != self.sr:   # remuestreo lineal: suficiente para voz
            x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * self.sr / sr0)), np.arange(len(x)), x).astype(np.float32)
        return cambiar_tono(x, self.sr, self.tono) if self.tono != 1.0 else x

    async def sintetizar(self, texto, lang):
        if lang == "ja":
            raise TTSError("piper no tiene voz japonesa")
        return await asyncio.to_thread(self._sync, solo_letras(texto) or texto), self.sr


class EdgeVoz(Voz):
    """edge-tts: voces neurales de Microsoft Edge, gratis y sin clave (nube, cero GPU). Una voz por idioma."""
    nombre = "edge"
    VOCES = {"es": "es-MX-DaliaNeural", "en": "en-US-AvaMultilingualNeural", "ja": "ja-JP-NanamiNeural"}

    def __init__(self, voces: dict[str, str] | None = None, tono: float = 1.0, sr: int = 24000,
                 velocidad: str = "+0%", altura: str = "+0Hz"):
        self.voces = {**self.VOCES, **(voces or {})}
        self.tono, self.sr, self.velocidad, self.altura = tono, sr, velocidad, altura

    def _cache(self, voz: str):
        from .cache_voz import Cache
        caches = self.__dict__.setdefault("_caches", {})
        if voz not in caches:
            caches[voz] = Cache(voz, self.velocidad, self.altura)
        return caches[voz]

    async def sintetizar(self, texto, lang):
        """Con caché (director/cache_voz.py): frase ya dicha → mp3 guardado; sin red → frase pegada con palabras grabadas."""
        import edge_tts
        from .cache_voz import decodificar
        voz = self.voces.get(lang) or self.voces["es"]
        txt = solo_letras(texto) or texto
        cache = self._cache(voz)
        mp3 = cache.leer(txt)
        if mp3 is None:
            buf, palabras = bytearray(), []
            try:
                com = edge_tts.Communicate(txt, voz, rate=self.velocidad, pitch=self.altura, boundary="WordBoundary")
                async for t in com.stream():
                    if t["type"] == "audio":
                        buf += t["data"]
                    elif t["type"] == "WordBoundary":   # offset/duration en unidades de 100 ns
                        a = t["offset"] / 1e7
                        palabras.append([t["text"], a, a + t["duration"] / 1e7])
            except Exception as e:  # noqa: BLE001  (sin red, edge caído, 403…)
                log.warning("edge tts falló (%s): pruebo pegar palabras de la caché", e)
                buf = bytearray()
            if not buf:
                x = await asyncio.to_thread(cache.pegar, txt, self.sr)
                if x is None:
                    if lang != "ja" and PiperVoz.disponible():   # último respaldo: TTS local por CPU, sin red
                        log.warning("edge y caché sin audio: digo la frase con Piper (local)")
                        return await PiperVoz(self.tono, self.sr).sintetizar(txt, lang)
                    raise TTSError(f"edge tts sin audio y faltan palabras en la caché: {cache.faltan(txt)[:5]}")
                return (cambiar_tono(x, self.sr, self.tono) if self.tono != 1.0 else x), self.sr
            mp3 = bytes(buf)
            await asyncio.to_thread(cache.guardar, txt, mp3, palabras)

        def _dec() -> np.ndarray:
            x = decodificar(mp3, self.sr)
            return cambiar_tono(x, self.sr, self.tono) if self.tono != 1.0 else x
        return await asyncio.to_thread(_dec), self.sr


class ConRespaldo(Voz):
    """XTTS si está listo; si no, gTTS para no dejarla muda, y se despierta XTTS para las frases siguientes."""

    def __init__(self, principal: XTTSVoz, respaldo: Voz, avisar=None):
        self.p, self.r, self.avisar = principal, respaldo, avisar or (lambda *_: None)
        self._despertando: asyncio.Task | None = None
        self.nombre = principal.nombre
        self._visto_listo = 0.0

    async def sintetizar(self, texto, lang):
        if time.monotonic() - self._visto_listo > 20 and not await self.p.listo():
            if not self._despertando or self._despertando.done():
                self.avisar("xtts_frio")
                self._despertando = asyncio.create_task(self.p.despertar())
            self.nombre = self.r.nombre
            return await self.r.sintetizar(texto, lang)
        try:
            out = await self.p.sintetizar(texto, lang)
            self._visto_listo, self.nombre = time.monotonic(), self.p.nombre
            return out
        except TTSError as e:
            log.warning("XTTS falló (%s): uso %s", e, self.r.nombre)
            self.avisar("xtts_error")
            self.nombre = self.r.nombre
            return await self.r.sintetizar(texto, lang)


# Voces que se pueden elegir en vivo en el perfil ligero (desplegable «Voz» de la consola; DOLLS_VOZ al arrancar).
PRESETS = {
    "gtts": {"motor": "google", "respaldo": "ninguno", "gtts_tld": {"es": "com.mx", "en": "com"}},   # CPU, nada de GPU/VRAM
    "xtts": {"motor": "xtts", "respaldo": "ninguno"},   # voz clonada de Joy (samplevoice.wav): ~2,2 GB de VRAM, no para jugar
}


async def mantener_xtts(xtts: "XTTSVoz", ultimo_turno, cada: float = 90, ventana: float = 600, activa=lambda: True) -> None:
    """Precalienta XTTS al arrancar y lo mantiene despierto mientras haya charla (un turno en los últimos `ventana` s):
    el orquestador lo apaga tras 2 min sin pedidos de día y volver cuesta ~30-40 s (y puede echar al 4B de la GPU)."""
    if activa():
        await xtts.despertar()
    while activa():
        await asyncio.sleep(cada)
        if activa() and time.monotonic() - ultimo_turno() < ventana:
            await xtts.despertar()


def principal_xtts(v: Voz) -> "XTTSVoz | None":
    return v if isinstance(v, XTTSVoz) else getattr(v, "p", None) if isinstance(v, ConRespaldo) else None


def crear(cfg_voz: dict, xtts_url: str, avisar=None) -> Voz:
    motor = cfg_voz.get("motor", "xtts")
    google = GoogleVoz(cfg_voz.get("gtts_tld"), float(cfg_voz.get("tono", 1.0)),
                       formantes=cfg_voz.get("formantes", "conservar") != "correr")   # "correr": voz de hombre desde gTTS
    if motor == "mudo":
        return MudoVoz()
    if motor == "google":
        return google
    if motor == "piper":  # 100 % local por CPU
        return PiperVoz(float(cfg_voz.get("tono", 1.0)))
    if motor == "edge":   # Microsoft Edge TTS gratis, sin GPU
        return EdgeVoz(cfg_voz.get("voces"), float(cfg_voz.get("tono", 1.0)),
                       velocidad=cfg_voz.get("velocidad", "+0%"), altura=cfg_voz.get("altura", "+0Hz"))
    if motor == "grok":   # nube xAI, sin GPU
        return GrokVoz(cfg_voz.get("voice", "eve"), float(cfg_voz.get("tono", 1.0)))
    xtts = XTTSVoz(xtts_url, cfg_voz.get("voice"), cfg_voz.get("speaker"), cfg_voz.get("temperatura"),
                   cfg_voz.get("velocidad"), float(cfg_voz.get("tono", 1.0)))
    if cfg_voz.get("respaldo", "ninguno") == "google":
        return ConRespaldo(xtts, google, avisar)
    xtts.avisar = avisar
    return xtts


__all__ = ["Voz", "XTTSVoz", "GoogleVoz", "GrokVoz", "EdgeVoz", "PiperVoz", "ConRespaldo", "crear", "idioma", "clean_for_speech"]
