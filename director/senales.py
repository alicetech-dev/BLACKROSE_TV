"""Señales de animación en el texto del LLM: etiquetas [emocion:x][gesto:y][mirar:z], *acciones*, emoji y
onomatopeyas. Devuelve la intención para joy_vmc y el texto limpio para la voz. La tabla vive en senales.yaml.

    s = Senales.cargar("joy", validas={"emociones": {...}, "gestos": {...}, "mirar": {...}})
    voz, intent, fuentes = s.frase("[emocion:feliz] Hola, Daddy~ 💋 *giggles*")
    # voz = "Hola, Daddy", intent = {"emocion": "feliz", "gesto": "patitas"}, fuentes = ["etiqueta", "emoji"]
"""
from __future__ import annotations

import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CAMPOS = ("emocion", "gesto", "mirar", "intensidad")
# El 4B a veces traduce el nombre de la etiqueta (emoção, olhar, emotion...): se aceptan alias.
ALIAS = {"emocion": "emocion", "emoción": "emocion", "emoção": "emocion", "emocao": "emocion", "emotion": "emocion",
         "emo": "emocion", "gesto": "gesto", "gesture": "gesto", "mirar": "mirar", "mirada": "mirar", "olhar": "mirar",
         "look": "mirar", "gaze": "mirar"}
TAG = re.compile(r"\[\s*(" + "|".join(sorted(ALIAS, key=len, reverse=True)) + r")\s*[:\s]\s*([^\]]*)\]", re.I)  # también [mirar derecha]
TAG_RARA = re.compile(r"\[\s*[^\W\d_]{2,12}\s*(?::[^\]]{0,30})?\]\s*:?")  # [voces]:, [olhar:x] sin alias...
BOLD = re.compile(r"(\*\*|__)(.+?)\1")
ACCION = re.compile(r"(?<![\w*])[*_]([^*_\n]{1,80})[*_](?![\w*])")
PAREN = re.compile(r"\(([^()\n]{1,80})\)")  # (se ríe), (giggles): acotación, no se dice
EMOTICON = re.compile(r"(?<!\w)(?:[:;=][\-^o]?[)(DPpO3/\\|*]+|<\\?/?3+|\^[_.\-]?\^|[>T;][_.\-]+[<T;]|[xX][dD]|[oO][_.\-][oO]|[uU][wW][uU]|[oO][wW][oO])(?!\w)")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍‼⁉]+")
RESTO_MD = re.compile(r"[*_`#~]+|^\s*[-•]\s+", re.M)


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if k in ("acciones", "onomatopeyas"):
            out[k] = list(v) + list(base.get(k, []))  # las de la doll se prueban primero
        elif isinstance(v, dict):
            out[k] = {**base.get(k, {}), **v}
        else:
            out[k] = v
    return out


class Senales:
    def __init__(self, tabla: dict, validas: dict | None = None):
        self.emoji = tabla.get("emoji", {})
        self.acciones = [(re.compile(p, re.I), d) for p, d in tabla.get("acciones", [])]
        self.onomatopeyas = [(re.compile(p, re.I), d) for p, d in tabla.get("onomatopeyas", [])]
        self.modos = tabla.get("modos", {})
        self.reacciones = tabla.get("reacciones", {})
        self.animos = tabla.get("animo", {})
        self.validas = {k: set(v) for k, v in (validas or {}).items()}

    @classmethod
    def cargar(cls, doll: str, validas: dict | None = None, path: str | None = None) -> "Senales":
        with open(path or os.path.join(HERE, "senales.yaml"), encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        tabla = _merge({k: v for k, v in raw.items() if k != "dolls"}, (raw.get("dolls") or {}).get(doll, {}))
        return cls(tabla, validas)

    def _valida(self, d: dict) -> dict:
        """Deja solo lo que esta doll sabe hacer (emociones/gestos/miradas de su joy_vmc)."""
        out = {}
        for k in CAMPOS:
            if k not in d or d[k] in (None, ""):
                continue
            v = d[k]
            if k == "intensidad":
                out[k] = min(max(float(v), 0.0), 1.0)
            elif k in ("emocion", "gesto", "mirar"):
                v = str(v).strip().lower()
                pool = self.validas.get({"emocion": "emociones", "gesto": "gestos", "mirar": "mirar"}[k])
                if pool is None or v in pool:
                    out[k] = v
        return out

    def frase(self, texto: str) -> tuple[str, dict, list[str]]:
        intent: dict = {}
        fuentes: list[str] = []

        def sumar(d: dict, fuente: str) -> None:
            d = self._valida(d)
            nuevo = {k: v for k, v in d.items() if k not in intent}
            if nuevo.keys() - {"intensidad"}:
                intent.update(nuevo)
                fuentes.append(fuente)

        # 1) etiquetas explícitas
        tags = {ALIAS[k.lower()]: v for k, v in TAG.findall(texto)}
        if tags:
            sumar(tags, "etiqueta")
        t = TAG_RARA.sub(" ", TAG.sub(" ", texto))
        t = EMOTICON.sub(" ", t)  # :3 <3 xD ^^ T_T uwu: antes de *acciones* (T_T tiene guion bajo)
        t = re.sub(r"[(\[][^()\[\]\n]{0,40}$", " ", t)  # acotación cortada por el tope de tokens: "(sonríe"
        t = re.sub(r"\*?\[[^\]]{0,40}$", " ", t)  # etiqueta cortada por el tope de tokens: "[gesto:pati"
        t = re.sub(r"\[[^\]\n]{1,30}\]", " ", t)  # cualquier otro corchete corto: acotación, no se dice
        t = BOLD.sub(r"\2", t)  # **énfasis**: se dice la palabra
        # 2) *acciones*: no se dicen
        for m in ACCION.finditer(t):
            for pat, d in self.acciones:
                if pat.search(m.group(1)):
                    sumar(d, "accion")
                    break
        t = ACCION.sub(" ", t)
        if t.count("*") % 2:  # "*se ríe" sin cierre (tope de tokens)
            t = re.sub(r"\*[^*\n]{0,40}$", " ", t)
        for m in PAREN.finditer(t):  # (acciones entre paréntesis): igual que *acciones*
            for pat, d in self.acciones:
                if pat.search(m.group(1)):
                    sumar(d, "accion")
                    break
        t = PAREN.sub(" ", t)
        # 3) emoji: no se dicen
        for ch in sorted({c for c in self.emoji if c in t}, key=t.index):
            sumar(self.emoji[ch], "emoji")
        t = EMOJI.sub(" ", t)
        # 4) onomatopeyas: sí se dicen
        for pat, d in self.onomatopeyas:
            if pat.search(t):
                sumar(d, "onomatopeya")
        # "~" de bimbo: antes de mayúscula termina la frase; si no, es una pausa (sin esto XTTS lee todo de corrido)
        t = re.sub(r"~+(?=\s*[A-ZÁÉÍÓÚÑ¿¡])", ".", t)
        t = re.sub(r"~+", ",", t)
        voz = re.sub(r"\s+([,.!?…])", r"\1", re.sub(r"\s{2,}", " ", RESTO_MD.sub(" ", t))).strip().rstrip(",").strip()
        voz = re.sub(r"([.!?…])[,.]+", r"\1", voz)
        voz = re.sub(r",(\s*,)+", ",", voz)  # ", ," donde había etiquetas o emoji
        return voz, intent, fuentes

    def reaccion(self, emocion_agente: str) -> dict:
        """Intención para la reacción inmediata (antes de que el LLM conteste)."""
        for pref, d in self.reacciones.items():
            if (emocion_agente or "").startswith(pref):
                return self._valida(d)
        return {}

    def animo(self, necesidad: str, energia: float | None = None) -> dict:
        d = dict(self.animos.get(necesidad, {}))
        if energia is not None and energia < 45:
            d["intensidad"] = float(d.get("intensidad", 1.0)) * 0.5
            d["mirar"] = "abajo"
        return self._valida(d)

    def modo(self, modo: str) -> dict:
        """Cómo se mueve en un modo del agente (trance/spa: lenta, mirada baja, sin gestos)."""
        return dict(self.modos.get(modo, {}))
