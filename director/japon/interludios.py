#!/usr/bin/env python3
"""INTERLUDIOS en japonés (≈1 min) para intercalar en TODOS los programas de la noche y mantener al público de Japón: invitación a Fast Penguin con su horario en hora de Japón,
capturas, hashtags, el circuito, español del día, aviso del traductor. El Director de TV mete 2 por programa pasando a la escena JAPON (Fuji + sakura + traducción).
Salida: director/japon/interludios.json   python -m director.japon.interludios [-f]"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys

from ..tv.productor import cargar, llm_con
from .guion import FOTOS, SISTEMA, laminas

log = logging.getLogger("japon.interludios")
HERE = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(HERE, "interludios.json")
H = "Chile (UTC−3) va 12 horas por detrás de Japón (UTC+9)."
INTER = [
    dict(id="fp_horario", fotos=["fp_1"], tag="FAST PENGUIN", n=8, abre="kuroki",
         datos=f"Recordatorio: mañana a las 06:00 hora de Chile (= 18:00 hora de Japón, el mismo día) Blackrose juega FAST PENGUIN en vivo. {H} Es gratis en Steam. Código de party: YDPYAU. Invitar a descargarlo y jugar con ella."),
    dict(id="fp_capturas", fotos=["fp_3"], tag="FAST PENGUIN", n=8, abre="joy",
         datos="Se muestra una captura del lobby de Fast Penguin: pingüinos con disfraces de piña (una morada con un cactus y otra amarilla), fondo de rejilla de neón. Es una carrera de supervivencia de hasta 40 jugadores; se gana pisando rivales para impulsarse. Gratis en Steam, party YDPYAU, mañana 18:00 hora de Japón."),
    dict(id="hashtags", fotos=["tags"], tag="HASHTAGS", n=8, abre="joy",
         datos="Leer los hashtags en voz alta y pedir que los usen al compartir: #BlackRoseTV #FastPenguin #AIVTuber #VTuber #ゲーム実況 #日本 #ForzaHorizon6. BlackRose TV es un canal de Twitch con presentadoras IA que emite 24 horas."),
    dict(id="suscribe", fotos=["fuji_sakura"], tag="SUSCRÍBETE", n=8, abre="kuroki",
         datos="Invitar con cariño a suscribirse al canal de Twitch BlackRose TV y activar las notificaciones; cada suscripción mantiene la señal encendida. Mencionar que en pantalla hay una barra de metas de suscriptores: con cada meta se desbloquea un stream especial o un juego nuevo."),
    dict(id="circuito", fotos=["fp_1"], tag="NUESTRO CIRCUITO", n=8, abre="joy",
         datos="Blackrose está construyendo su propio circuito de carreras, un mundo 3D en desarrollo; todavía es PRIVADO y no está publicado, no hay fecha. Cuando se abra, el público suscrito se enterará primero. Mientras tanto, invitar a jugar Fast Penguin con la party YDPYAU."),
    dict(id="traductor", fotos=["fuji_amanecer"], tag="コメントOK", n=8, abre="kuroki",
         datos="Aviso: pueden escribir comentarios en japonés en el chat de Twitch; el canal los traduce automáticamente al español y los muestra en pantalla. Joy y Kuroki hablan japonés en algunos momentos y todo lo que dicen aparece traducido al español abajo. Animarlos a escribir."),
    dict(id="espanol", fotos=["lista_espanol"], tag="ESPAÑOL", n=8, abre="joy",
         datos="Mini lección de español: Hola = こんにちは; Gracias = ありがとう; Buenas noches = こんばんは; ¡Qué rápido! = なんて速い!; Vamos a jugar = 一緒に遊ぼう. Kuroki lo repite con humor."),
    dict(id="forza", fotos=["tokio"], tag="FORZA HORIZON 6", n=8, abre="kuroki",
         datos="Forza Horizon 6 es el juego de carreras de mundo abierto de Playground Games ambientado en Japón (mapa «Horizon Japan», una versión ficticia de Japón con Tokio como eje). Salió el 19 de mayo de 2026 para Xbox Series X|S y PC. Preguntar al chat si lo han jugado. No inventar más datos."),
    dict(id="horarios", fotos=["lista_horarios"], tag="HORARIOS", n=8, abre="joy",
         datos=f"{H} La programación nocturna de BlackRose TV (hora de Chile → hora de Japón) termina con Fast Penguin a las 06:00 → 18:00. Los programas duran unos 40 minutos y hay pausas entre ellos. Invitar a quedarse con ellas."),
]


async def uno(x: dict) -> dict | None:
    otra = "kuroki" if x["abre"] == "joy" else "joy"
    u = (f"INTERLUDIO CORTO: {x['tag']}.\nHOJA DE DATOS (única fuente de hechos):\n{x['datos']}\n\nEscribe {x['n']} intervenciones alternadas entre joy y kuroki (empieza {x['abre']}, sigue {otra}), de 40 a 70 caracteres japoneses cada una, "
         "en JAPONÉS natural, cálido y breve, con su traducción fiel al español. Es un corte dentro de otro programa: sin saludar de nuevo ni despedirse. "
         'Devuelve SOLO este JSON: {"lineas":[{"quien":"joy","ja":"…","es":"…"}]}')
    for _ in range(2):
        d = await llm_con(SISTEMA, u, 2500, 0.8)
        ls = []
        for y in (d or {}).get("lineas", []) if isinstance(d, dict) else []:
            ja, es = re.sub(r"\s+", " ", str(y.get("ja", ""))).strip(), re.sub(r"\s+", " ", str(y.get("es", ""))).strip()
            if y.get("quien") in ("joy", "kuroki") and len(re.findall(r"[぀-ヿ一-鿿]", ja)) >= 4 and len(es) > 5:
                ls.append({"quien": y["quien"], "ja": ja[:200], "es": es[:300]})
        if len(ls) >= 5:
            lam = laminas({"fotos": x["fotos"], "ja": x["tag"], "es": x["tag"]})
            for l in lam:
                l["tag"] = "日本 · " + x["tag"]
            return {"tipo": "ja_charla", "interludio": True, "id": "inter_" + x["id"], "titulo_ja": x["tag"], "titulo_es": x["tag"], "laminas": lam, "lineas": ls}
    return None


async def main(forzar: bool) -> None:
    if os.path.exists(RUTA) and not forzar:
        return
    sem = asyncio.Semaphore(3)

    async def c(x):
        async with sem:
            r = await uno(x)
            log.info("%s: %s", x["id"], f"{len(r['lineas'])} líneas" if r else "FALLÓ")
            return r
    res = [r for r in await asyncio.gather(*(c(x) for x in INTER)) if r]
    json.dump({"items": res}, open(RUTA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log.info("✔ %d interludios", len(res))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(main("-f" in sys.argv))
