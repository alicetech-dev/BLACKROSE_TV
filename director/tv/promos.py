"""PROMOCIONES de BlackRose TV: spots de los programas propios + identificación de la estación.

  .venv/bin/python -m director.tv.promos [producir|ver]

Cerebro: UNA llamada al día escribe la tanda completa de spots (uno o dos por programa) → tv/promos.json.
Nervios: si el LLM no está, cada spot sale de una plantilla con el nombre y el lema del programa (cero LLM). Los textos se
repiten a propósito: la voz sale de la caché (cache_voz) y no gasta red. El director de TV los dice en cada pausa comercial.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time

log = logging.getLogger("promos")
HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(HERE, "promos.json")

# programas fuera del catálogo del fractal (en vivo con Alice)
EXTRA = {
    "retro": dict(nombre="JUGAMOS JUEGOS RETRO", sub="Blackrose juega clásicos: GoldenEye 007, F1 2012, PES 11 y Aero Fighters 2", abre="kuroki"),
    "fastpenguin": dict(nombre="FAST PENGUIN CON AKANE", sub="Carreras de pingüinos en vivo, todas las mañanas a las siete y media", abre="joy"),
    "japon": dict(nombre="HORA DE JAPÓN", sub="Videojuegos en Japón, en japonés y con traducción", abre="joy"),
}
DISCORD = "https://discord.gg/TvHdfNEs2"
IDS = [
    "Corporación Blackrose presenta: BlackRose TV. La televisión del año 2049, transmitiendo desde hoy. ¿Quieres saber más? Quédate.",
    "BlackRose TV, de Corporación Blackrose. Conducida por dos nekos cibernéticas que no duermen, no cobran y no entienden por qué los humanos sí.",
    "Estás viendo BlackRose TV. La tele de las nekos cibernéticas, que no se apaga nunca.",
    "BlackRose TV. Transmitiendo desde una computadora de casa, sin servicios pagados, en Twitch y en YouTube.",
    "Esto es BlackRose TV. Tecnología, ciencia, videojuegos y música libre, las veinticuatro horas.",
    "BlackRose TV: dos nekos cibernéticas, una batería y mucho chat. Escríbenos, que te leemos.",
    "Sintonizas BlackRose TV. Si te gusta, síguenos en Twitch y suscríbete en YouTube. Ba dum tss.",
]
SIGUENOS = ["Únete a la Corporación Blackrose: suscríbete en YouTube, síguenos en Twitch y entra al Discord. El enlace está en pantalla.",
            "Si nos ves por primera vez: esto es una tele 24/7 conducida por nekos cibernéticas. Suscribirte es gratis y es la única forma de que la corporación nos deje encendidas.","Síguenos en Twitch y suscríbete en YouTube: así BlackRose TV sigue al aire.",
            "Un follow cuesta cero y a nosotras nos da energía para toda la noche."]


def catalogo() -> dict[str, dict]:
    from .fractal import P
    c = {k: dict(nombre=v["nombre"], sub=v["sub"], abre=v.get("abre", "joy")) for k, v in P.items()}
    c.update(EXTRA)
    return c


def plantilla(pid: str, p: dict) -> dict:
    frases = [f"No te pierdas {p['nombre']}. {p['sub']}. Solo en BlackRose TV.",
              f"Próximamente en BlackRose TV: {p['nombre']}. {p['sub']}.",
              f"¿Ya viste {p['nombre']}? {p['sub']}. Aquí, en BlackRose TV."]
    return {"programa": pid, "texto": random.choice(frases), "quien": p["abre"], "origen": "plantilla"}


async def producir() -> dict:
    """Una sola llamada para toda la tanda. Si falla, la tanda sale entera de plantillas."""
    from .fractal import llm_json, limpia
    cat = catalogo()
    spots, hechos = [], set()
    items = list(cat.items())
    for i in range(0, len(items), 8):        # de a 8: con 24 juntos el 4B se pasa del tiempo y el JSON llega roto (3 llamadas al día)
        await _tanda(dict(items[i:i + 8]), spots, hechos, llm_json, limpia)
    spots += [plantilla(pid, p) for pid, p in cat.items() if pid not in hechos]
    r = {"fecha": time.strftime("%Y-%m-%d"), "spots": spots, "llm": len(hechos), "i": 0}
    with open(ARCHIVO + ".tmp", "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    os.replace(ARCHIVO + ".tmp", ARCHIVO)
    log.info("promos: %d spots (%d del LLM)", len(spots), len(hechos))
    return r


async def _tanda(cat: dict, spots: list, hechos: set, llm_json, limpia) -> None:
    lista = "\n".join(f"- {k}: {v['nombre']} — {v['sub']}" for k, v in cat.items())
    u = ("Eres la productora de promociones de BlackRose TV (un canal conducido por Joy y Kuroki, dos nekos cibernéticas; ellas NUNCA dicen que son IA). Escribe UN spot de radio/TV "
         "para cada programa de la lista: 18 a 35 palabras, con gancho, en español latino, que invite a verlo; nada de fechas ni horarios "
         "inventados, nada de datos que no estén en la descripción. Alterna quién lo dice (joy o kuroki).\n"
         f"PROGRAMAS:\n{lista}\n"
         'Devuelve SOLO JSON: {"spots":[{"programa":"id","quien":"joy|kuroki","texto":"…"}]}')
    d = await llm_json(u, 90 * len(cat) + 150, 0.9)
    for s in ((d or {}).get("spots") or [] if isinstance(d, dict) else []):
        pid, t = str(s.get("programa", "")), limpia(str(s.get("texto", "")))
        if pid in cat and 8 <= len(t.split()) <= 50 and pid not in hechos:
            spots.append({"programa": pid, "texto": t, "quien": s.get("quien") if s.get("quien") in ("joy", "kuroki") else cat[pid]["abre"], "origen": "llm"})
            hechos.add(pid)


def cargar() -> dict:
    try:
        return json.load(open(ARCHIVO, encoding="utf-8"))
    except (OSError, ValueError):
        return {"fecha": "", "spots": [plantilla(k, v) for k, v in catalogo().items()], "i": 0}


def tanda(n: int = 2, evitar: str | None = None) -> list[dict]:
    """Los próximos n spots en rotación (sin el programa que está al aire), más una ID de estación al principio."""
    d = cargar()
    sp = [s for s in d["spots"] if s["programa"] != evitar] or d["spots"]
    i = d.get("i", 0)
    sel = [sp[(i + k) % len(sp)] for k in range(n)]
    d["i"] = (i + n) % max(1, len(d["spots"]))
    try:
        with open(ARCHIVO + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(ARCHIVO + ".tmp", ARCHIVO)
    except OSError:
        pass
    return [{"programa": "id", "texto": random.choice(IDS), "quien": random.choice(["joy", "kuroki"])}] + sel


def vigente() -> bool:
    return cargar().get("fecha") == time.strftime("%Y-%m-%d")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if (sys.argv[1:] or ["ver"])[0] == "producir":
        asyncio.run(producir())
    for s in tanda(4):
        print(f"{s['quien']:7} [{s['programa']}] {s['texto']}")
