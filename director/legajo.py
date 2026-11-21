"""El legajo de la operadora en el Instituto: su progreso real (noches en el dormitorio VR, archivos de BambiCloud
escuchados enteros), guardado en director/legajo.json. Las dolls lo reciben resumido y lo nombran a veces; al cruzar
un hito (3 noches, 10 archivos...) le entregan un trofeo (turno espontáneo "trofeo", el premio lo inventan ellas).
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta

HITOS_NOCHES = (1, 3, 7, 14, 21, 30, 50, 75, 100, 150, 200, 365)
HITOS_ARCHIVOS = (1, 5, 10, 25, 50, 75, 100, 150, 200, 300, 500)
HITOS_HORAS = (5, 10, 25, 50, 100, 200)


def noche_de(ahora: datetime | None = None) -> str:
    """La noche cambia a las 6 de la mañana (igual que la lección de la Bible)."""
    return ((ahora or datetime.now()) - timedelta(hours=6)).date().isoformat()


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


class Legajo:
    def __init__(self, path: str):
        self.path = path
        self.d = {"noches": [], "archivos": {}, "segundos": 0, "trofeos": []}
        try:
            with open(path, encoding="utf-8") as f:
                self.d.update(json.load(f))
        except (OSError, ValueError):
            pass

    def _guardar(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def _hito(self, que: str) -> str:
        self.d["trofeos"] = (self.d["trofeos"] + [{"noche": noche_de(), "por": que}])[-50:]
        return que

    def racha(self) -> int:
        noches, n, dia = set(self.d["noches"]), 0, datetime.fromisoformat(noche_de())
        while (dia - timedelta(days=n)).date().isoformat() in noches:
            n += 1
        return n

    def noche(self) -> str:
        """Estás en el dormitorio esta noche. Devuelve el hito cruzado ('' si no hay)."""
        hoy = noche_de()
        if hoy in self.d["noches"]:
            return ""
        self.d["noches"].append(hoy)
        n, r = len(self.d["noches"]), self.racha()
        hito = ""
        if n in HITOS_NOCHES:
            hito = self._hito(f"her {ordinal(n)} night in the dorm")
        elif r in (3, 7, 14, 30) and r < n:
            hito = self._hito(f"{r} nights in a row in the dorm without missing one")
        self._guardar()
        return hito

    def archivo(self, nombre: str, segundos: float) -> str:
        """Un archivo de BambiCloud escuchado entero. Devuelve el hito cruzado ('' si no hay)."""
        nombre = nombre.strip()[:120]
        if not nombre:
            return ""
        horas0 = self.d["segundos"] // 3600
        self.d["archivos"][nombre] = self.d["archivos"].get(nombre, 0) + 1
        self.d["segundos"] += max(0, int(segundos))
        total, veces, horas = sum(self.d["archivos"].values()), self.d["archivos"][nombre], self.d["segundos"] // 3600
        hito = ""
        if total in HITOS_ARCHIVOS:
            hito = self._hito(f"her {ordinal(total)} trance file listened all the way through")
        elif veces in (5, 10, 25):
            hito = self._hito(f'listening to "{nombre}" {veces} times — it\'s really sinking in')
        elif horas > horas0 and horas in HITOS_HORAS:
            hito = self._hito(f"{horas} hours of conditioning files")
        self._guardar()
        return hito

    def resumen(self) -> str:
        """En inglés, corto: para el prompt (DOLL_LEGAJO). Vacío si todavía no hay nada."""
        noches, archivos = len(self.d["noches"]), self.d["archivos"]
        if not noches and not archivos:
            return ""
        partes = [f"{noches} night{'s' if noches != 1 else ''} in the dorm"]
        if (r := self.racha()) > 1:
            partes[-1] += f" ({r} in a row)"
        if archivos:
            total = sum(archivos.values())
            fav, veces = Counter(archivos).most_common(1)[0]
            partes.append(f"{total} trance files finished ({self.d['segundos'] // 3600} h), most played: \"{fav}\" ×{veces}")
        if self.d["trofeos"]:
            partes.append("recent milestones: " + "; ".join(t["por"] for t in self.d["trofeos"][-3:]))
        return ", ".join(partes)
