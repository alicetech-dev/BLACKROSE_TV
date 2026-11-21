"""Escenas del guion: tú escribes el texto y va directo a la voz (sin pasar por la IA), con la animación que pide la
escena (pose, baile, cara, mirada, cuántas manos). Funciona con la IA prendida o apagada.

Formato del texto:
  · una línea en blanco = pausa larga (entre noticias, entre estrofas)
  · `[pausa]` o `[pausa 2.5]` = pausa en segundos, en cualquier parte
  · `Joy: hola` / `Bambi: hola` al principio de una línea cambia de quien habla (las líneas siguientes siguen con ella)
  · lo de siempre: *acciones*, emojis y [emocion:x] mueven la cara y los gestos de esa frase

Cada escena se puede cambiar o ampliar en `escenas:` del yaml de la consola (se mezcla por id sobre estas).
Claves: label, icono, desc, pose (parada|sentada), baile (nombre o 0..1) + tempo (bpm), emocion, mirar, manos (0 = sin
manos al hablar, 0..1), gestos (false: ni los de las etiquetas ni los automáticos), por_linea (cada línea es un verso),
pausa (s entre párrafos), pausa_linea (s entre versos).
"""
from __future__ import annotations

import copy
import re

from .frases import Cortador

ESCENAS: dict[str, dict] = {
    "hablar": {"label": "Hablar a cámara", "icono": "🎥", "desc": "mira a cámara, manos sueltas, cara simpática",
               "emocion": "feliz", "mirar": "camara", "manos": 0.5, "pausa": 0.7},
    "noticias": {"label": "Leer noticias", "icono": "📰", "desc": "seria y a cámara, pocas manos; una noticia por párrafo",
                 "emocion": "neutral", "mirar": "camara", "manos": 0.2, "pausa": 1.3},
    "cantar": {"label": "Cantar bailando", "icono": "🎤", "desc": "baila al compás mientras dice cada verso (una línea = un verso)",
               "pose": "parada", "baile": "suave", "tempo": 100, "emocion": "alegre", "manos": 0, "gestos": False,
               "por_linea": True, "pausa_linea": 0.25, "pausa": 1.0},
    "cuento": {"label": "Contar un cuento", "icono": "📖", "desc": "sentada, tranquila, mirando a cámara",
               "pose": "sentada", "emocion": "feliz", "mirar": "camara", "manos": 0.3, "pausa": 1.1},
    "libre": {"label": "Solo texto", "icono": "💬", "desc": "sin tocar pose ni cara: solo lo que digan las etiquetas del texto",
              "pausa": 0.6},
}

_PAUSA = re.compile(r"\[pausa(?:\s+([\d.]+))?\]", re.I)


def escenas(cfg: dict | None = None) -> dict[str, dict]:
    """ESCENAS + lo que el yaml cambie o agregue (por id, clave por clave)."""
    out = copy.deepcopy(ESCENAS)
    for sid, over in ((cfg or {}).get("escenas") or {}).items():
        out.setdefault(sid, {"label": sid}).update(over or {})
    for sid, e in out.items():
        e["id"] = sid
    return out


def dividir(texto: str, escena: dict) -> list[str | float]:
    """Texto -> frases para la voz (str) y pausas en segundos (float), en orden."""
    out: list[str | float] = []
    por_linea = bool(escena.get("por_linea"))
    parrafos = [p for p in re.split(r"\n[ \t]*\n", texto.strip()) if p.strip()]
    for i, par in enumerate(parrafos):
        trozos = _PAUSA.split(par)  # texto, seg, texto, seg, ...
        for j, tz in enumerate(trozos):
            if j % 2:
                out.append(float(tz or 1.0))
                continue
            lineas = [x for x in tz.split("\n") if x.strip()] if por_linea else [tz]
            for k, linea in enumerate(lineas):
                c = Cortador(primera_max=10 ** 6)
                out += c.push(linea) + c.flush()
                if k < len(lineas) - 1:
                    out.append(float(escena.get("pausa_linea", 0.3)))
        if i < len(parrafos) - 1:
            out.append(float(escena.get("pausa", 0.8)))
    return out


def partir_guion(texto: str, nombres: dict[str, set[str]], defecto: str) -> list[tuple[str, str]]:
    """[(doll, texto)]: `Joy: ...` al principio de una línea cambia de quien habla; lo anterior es de `defecto`.
    nombres: id de doll -> sus nombres/alias en minúscula."""
    pat = {d: re.compile(rf"^\s*@?(?:{'|'.join(re.escape(a) for a in sorted(n, key=len, reverse=True))})\s*:\s*", re.I)
           for d, n in nombres.items() if n}
    segs: list[tuple[str, list[str]]] = [(defecto, [])]
    for linea in texto.splitlines():
        for d, p in pat.items():
            m = p.match(linea)
            if m:
                segs.append((d, [linea[m.end():]]))
                break
        else:
            segs[-1][1].append(linea)
    return [(d, "\n".join(ls).strip()) for d, ls in segs if "\n".join(ls).strip()]
