"""PENSADOR de BlackRose TV: los pensamientos NO verbalizados de Joy y Kuroki, con el 9B (modo «profundo» del cerebro,
el ThinkPad por CPU; si no está, el cerebro lo pasa al 4B). Reemplaza a grok-coord: cero APIs de pago.

Cada CADA s (20 min) piensa; entre medio investiga sin parar (hojas de datos de los próximos programas):
  1. mira qué está al aire (tv/estado.json), qué viene en la cartelera y el chat reciente (:8822/api/chat)
  2. INVESTIGA: titulares reales (Google News RSS) del próximo programa que tenga un pie en la actualidad
  3. piensa (1 pedido profundo, ≤700 tokens): reflexión interna + semillas nuevas para los próximos programas + directriz de tono
  4. escribe: logs/pensamientos.jsonl (diario interno, nunca sale al aire), tv/semillas_extra.json (fractal.py las usa primero),
     tv/coordinacion.json (directriz + temas)
  python -m director.tv.pensador [demonio|una]
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import sys
import time

import aiohttp

from ..show_kuroki import titulares
from .fractal import EXTRA, P, hay_hoja, investigar, llm_json, semillas_de
from .productor import USADOS
from .productor import CARTELERA, COORD, cargar, fecha_noche, limpia

log = logging.getLogger("pensador")
HERE = os.path.dirname(os.path.abspath(__file__))
DIARIO = os.path.join(HERE, "..", "..", "logs", "pensamientos.jsonl")
CADA = int(os.getenv("PENSADOR_CADA", "1200"))     # un pensamiento cada 20 min; el resto del tiempo, investiga


async def chat_reciente() -> list[str]:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s, s.get("http://127.0.0.1:8822/api/chat") as r:
            ms = await r.json(content_type=None)
        return [f"{m.get('autor')}: {str(m.get('texto'))[:120]}" for m in ms if time.time() - m.get("t", 0) < 3600][-10:]
    except Exception:  # noqa: BLE001
        return []


def proximos(n: int = 4) -> list[dict]:
    c = cargar(CARTELERA, {"bloques": []})
    base = dt.datetime.strptime(fecha_noche(), "%Y-%m-%d").date()
    ahora, out = dt.datetime.now(), []
    for b in c["bloques"]:
        h, m = map(int, b["ini"].split(":"))
        a = dt.datetime.combine(base + dt.timedelta(days=1 if h < 12 else 0), dt.time(h, m))
        if a > ahora and b.get("programa") in P:
            out.append(b)
    return out[:n]


async def pensar() -> dict | None:
    est = cargar(os.path.join(HERE, "estado.json"), {})
    prox = proximos()
    chat = await chat_reciente()
    inv, objetivo = [], None
    for b in prox:                         # investiga el primero que tenga actualidad
        v = P[b["programa"]]
        if v.get("rss"):
            objetivo = b
            inv = await titulares(v["rss"][:2], set(), 5)
            break
    previo = []
    try:
        previo = [json.loads(l).get("pensamiento", "") for l in open(DIARIO, encoding="utf-8").readlines()[-3:]]
    except (OSError, ValueError):
        pass
    progs = ", ".join(f"{b['programa']} ({b['nombre']}, {b['ini']})" for b in prox) or "programación habitual"
    u = ("Eres la MENTE INTERNA de Joy y Kuroki, las dos nekos cibernéticas que conducen BlackRose TV (nunca dicen que son IA), un canal 24/7. Esto NO se dice al aire: es tu reflexión privada, profunda y honesta.\n"
         f"Ahora al aire: {est.get('bloque', '?')} · {est.get('item', '?')}.\nPróximos programas: {progs}.\n"
         f"Chat reciente: {' | '.join(chat) or '(silencio)'}.\n"
         + (f"Investigación para {objetivo['nombre']}: " + " | ".join(f"{x['titulo']} ({x['fuente']})" for x in inv) + "\n" if inv else "")
         + (f"Tus últimos pensamientos: {' / '.join(p[:160] for p in previo)}\n" if previo else "")
         + "Reflexiona: qué está funcionando, qué le interesa al público, qué conviene profundizar o evitar. Luego propone, para cada próximo programa, "
         "2 semillas de episodio NUEVAS, concretas y verificables (títulos de hasta 9 palabras; nada de salud, elecciones ni tragedias). Y una directriz breve de tono para la próxima hora.\n"
         'Devuelve SOLO JSON: {"pensamiento":"3 a 5 frases","animo":"una palabra","directriz":"una frase","semillas":{"<programa>":["…","…"]}}')
    t0 = time.time()
    d = await llm_json(u, 450, 0.8, profundo=True)
    if not isinstance(d, dict):
        log.warning("sin pensamiento esta vuelta")
        return None
    d["t"], d["seg"], d["investigado"] = time.strftime("%Y-%m-%d %H:%M:%S"), round(time.time() - t0), [x["titulo"] for x in inv]
    os.makedirs(os.path.dirname(DIARIO), exist_ok=True)
    with open(DIARIO, "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    extra = cargar(EXTRA, {})
    sem = d.get("semillas") if isinstance(d.get("semillas"), dict) else {}
    for pid, lst in sem.items():
        if pid in P and isinstance(lst, list):
            nuevas = [limpia(s)[:90] for s in lst if isinstance(s, str) and 6 < len(s) < 120]
            extra[pid] = (extra.get(pid, []) + [s for s in nuevas if s not in extra.get(pid, [])])[-30:]
    json.dump(extra, open(EXTRA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if d.get("directriz"):
        json.dump({"directriz": limpia(str(d["directriz"]))[:300], "temas": {}, "t": d["t"], "fuente": "pensador local"}, open(COORD, "w", encoding="utf-8"), ensure_ascii=False)
    log.info("💭 (%ds, %s) %s", d["seg"], d.get("animo"), str(d.get("pensamiento"))[:160])
    return d


async def preparar_hoja() -> bool:
    """Investiga por adelantado la próxima semilla sin hoja de los próximos programas (el 9B es lento: va horas adelante)."""
    import random
    usados = cargar(USADOS, {})
    for b in proximos(6):
        pid = b["programa"]
        for s in semillas_de(pid, usados, random.Random(0))[:3]:
            if not hay_hoja(s):
                t0 = time.time()
                h = await investigar(P[pid], s, profundo=True)
                log.info("📚 hoja de «%s» para %s: %s (%.0f s)", s[:50], pid, f"{len(h['hechos'])} hechos" if h else "falló", time.time() - t0)
                return bool(h)
    return False


async def demonio() -> None:
    """Pensar cada ~CADA s; entre pensamientos, investigar sin parar (hojas de datos para los próximos programas)."""
    ultimo = 0.0
    while True:
        try:
            if time.time() - ultimo >= CADA:
                ultimo = time.time()
                await pensar()
            elif not await preparar_hoja():
                await asyncio.sleep(60)
        except Exception:  # noqa: BLE001
            log.exception("el pensador tropezó; sigue")
            await asyncio.sleep(30)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(pensar() if (sys.argv[1:] or ["demonio"])[0] == "una" else demonio())
