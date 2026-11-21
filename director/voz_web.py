"""Las voces también para el visor VR del celular: cada frase que suena en la PC se guarda como WAV (las últimas
40) y se sirve en GET /voz/{id}.wav. La doll avisa dos veces por el WebSocket de la consola:
  {"type": "voz", "doll", "id"}          apenas la frase está sintetizada (el celular la baja por adelantado)
  {"type": "voz_t", "doll", "id", "t"}   el instante (time.time() de la PC) en que empieza a sonar en la PC
El celular la reproduce en t + retraso, con la animación del cuerpo atrasada lo mismo: la boca sigue sincronizada.
"""
from __future__ import annotations

import collections
import io
import itertools
import os
import wave

import numpy as np
from aiohttp import web

_wavs: collections.OrderedDict[str, bytes] = collections.OrderedDict()
_ids = itertools.count(1)


def guardar(audio: np.ndarray, sr: int, texto: str = "", lang: str = "", doll: str = "") -> str:
    x = np.clip(np.asarray(audio, np.float32).reshape(-1), -1, 1)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes((x * 32767).astype("<i2").tobytes())
    vid = str(next(_ids))
    _wavs[vid] = buf.getvalue()
    if texto.strip():
        _al_disco(buf.getvalue(), texto, lang or "en", doll)
    while len(_wavs) > 40:
        _wavs.popitem(last=False)
    return vid


def _al_disco(data: bytes, texto: str, lang: str, doll: str) -> None:
    """También a la caché de voces del visor (vr/voces.py): lo que XTTS ya hizo vuelve como charla de las NPCs."""
    try:
        from vr import voces as V
        vid = V.clave(texto, "mujer", lang)
        if os.path.exists(V.ruta(vid)):
            return
        os.makedirs(V.DIR, exist_ok=True)
        with open(V.ruta(vid), "wb") as f:
            f.write(data)
        V.anotar(vid, texto, "mujer", lang, "doll", doll)
    except Exception as e:  # la caché es un extra: nunca corta la voz
        print("voz_web: no guardé en la caché:", e)


async def servir(req: web.Request) -> web.Response:
    data = _wavs.get(req.match_info["id"])
    if data is None:
        raise web.HTTPNotFound()
    return web.Response(body=data, content_type="audio/wav", headers={"Cache-Control": "no-store"})
