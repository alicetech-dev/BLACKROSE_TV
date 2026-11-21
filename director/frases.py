"""Corta el stream del LLM en frases para sintetizarlas una por una (la frase N+1 se sintetiza mientras suena la N).

La primera frase se corta antes (en una coma o pausa) para empezar a hablar cuanto antes. No se corta dentro de una
etiqueta [emocion:x] ni de una *acción*. Con `min_len`, un pedazo con menos texto pronunciable que eso se junta con lo
que sigue: XTTS alarga y deforma las frases muy cortas ("Uy, qué lindo." sola dura 2-4 veces lo normal).
"""
from __future__ import annotations

import re

FIN = re.compile(r"([.!?…]+[\"'”)\]]*)(\s+|$)|\n+")
PAUSA = re.compile(r"[,;:~—–]\s+")
ABREV = re.compile(r"\b(Mr|Mrs|Ms|Dr|Sr|Sra|St|vs|etc|p\.ej)\.$", re.I)


_NO_DICHO = re.compile(r"\[[^\]]*\]|\*[^*]*\*")


def _hablable(t: str) -> int:
    """Largo de lo que se va a decir (sin etiquetas ni *acciones*)."""
    return len(_NO_DICHO.sub("", t).strip())


def _abierto(t: str) -> bool:
    """True si el texto termina dentro de una etiqueta [..] o una *acción* sin cerrar."""
    return t.count("[") > t.count("]") or t.count("*") % 2 == 1


class Cortador:
    def __init__(self, primera_max: int = 48, max_len: int = 220, min_len: int = 0):
        self.buf, self.primera, self.primera_max, self.max_len, self.min_len = "", True, primera_max, max_len, min_len

    def _corto(self, t: str) -> bool:
        """Tiene algo que decir pero muy poco (solo etiquetas o *acciones* sí se pueden mandar solas)."""
        return 0 < _hablable(t) < self.min_len

    def push(self, delta: str) -> list[str]:
        self.buf += delta
        out = []
        while True:
            corte = self._corte()
            if corte is None:
                break
            frase, self.buf = self.buf[:corte].strip(), self.buf[corte:]
            if frase:
                out.append(frase)
                self.primera = False
        return out

    def flush(self) -> list[str]:
        frase, self.buf = self.buf.strip(), ""
        return [frase] if frase else []

    def _corte(self) -> int | None:
        for m in FIN.finditer(self.buf):
            fin = m.end()
            cabeza = self.buf[:m.start(1) if m.group(1) else m.start()] + (m.group(1) or "")
            if m.group(1) and ABREV.search(cabeza):
                continue
            if m.group(2) == "" and m.group(1):
                return None  # "Hola." al final del buffer: puede venir "..." o una comilla; se espera al próximo trozo
            if _abierto(self.buf[:fin]) or self._corto(self.buf[:fin]):
                continue
            return fin
        # sin fin de frase: la primera se corta en una pausa, las demás si se hacen muy largas
        limite = self.primera_max if self.primera else self.max_len
        if len(self.buf) > limite:
            pausas = [m.end() for m in PAUSA.finditer(self.buf)
                      if _hablable(self.buf[:m.end()]) >= max(8, self.min_len) and not _abierto(self.buf[:m.end()])]
            if pausas:
                return pausas[0] if self.primera else pausas[-1]
            if not self.primera and len(self.buf) > self.max_len * 1.5:
                esp = self.buf.rfind(" ", 0, self.max_len)
                return esp if esp > 0 else None
        return None
