"""CONSOLA DEL DIRECTOR DEL CANAL — BlackRose TV. Una sola página para manejar el canal autogenerado.

  .venv/bin/python -m director.consola_canal        (servicio brtv-consola.service)  →  http://127.0.0.1:8834

No reemplaza a nadie: lee el estado de cada pieza y escribe en los mismos archivos/APIs que ya usan.
  · modo del canal: AUTO (la TV conduce) · EN VIVO (Alice transmite; tv.sh envivo) · PAUSA (pantalla de pausa, TV detenida)
  · cartelera: qué hay ahora y después; reprogramar un bloque futuro (otro programa) o producirlo de nuevo
  · temáticas: temas por programa y directriz de tono → director/tv/consola.json (el fractal los usa primero)
  · hablar: que Joy o Kuroki digan algo ya (voz + subtítulo), ID de estación, spot, aviso «vuelvo en…»
  · escena de OBS, juego retro y «qué pasa ahora» (director/tv/ahora.json: lo leen el chat y Kuroki)
  · chat (Twitch + YouTube) y sugerencias para Alice, salud y nivel de degradación, tendencias
  · INSTALACIONES (20-nov): plano de los sets del estudio Unity 2049 en vivo, cortar de set/cámara, encender el estudio
  · ESTUDIO DE PROGRAMAS (20-nov): la usuaria arma programas tramo a tramo (set + cámara + líneas) y los programa en la cartelera
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import subprocess
import time
import urllib.parse

import aiohttp
from aiohttp import web

log = logging.getLogger("consola")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TV = os.path.join(RAIZ, "director", "tv")
LOGS = os.path.join(RAIZ, "logs")
WEB = os.path.join(RAIZ, "director", "web", "consola")
F = {k: os.path.join(TV, v) for k, v in dict(cartelera="cartelera.json", estado="estado.json", consola="consola.json", ahora="ahora.json",
                                             tend="tendencias.json", promos="promos.json").items()}
ENVIVO, PAUSA = os.path.join(LOGS, "envivo"), os.path.join(LOGS, "pausa_canal")
RETRO = "http://127.0.0.1:8832"
PUERTO = int(os.getenv("CONSOLA_PUERTO", "8834"))
ESTUDIO = "http://127.0.0.1:8836"
AIRE = os.path.expanduser("~/BlackroseTV_build/aire.sh")
MIS = os.path.join(TV, "mis_programas.json")
WPS = 2.3      # palabras por segundo de la voz (igual que fractal.WPS)


def leer(p: str, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return d


def escribir(p: str, d) -> None:
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def sh(*cmd: str, timeout: float = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=RAIZ)
        return (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return str(e)


async def jget(ses: aiohttp.ClientSession, url: str, t: float = 2):
    try:
        async with ses.get(url, timeout=aiohttp.ClientTimeout(total=t)) as r:
            return await r.json(content_type=None)
    except Exception:  # noqa: BLE001
        return None


async def obs(tipo: str, datos: dict | None = None) -> dict | None:
    from director.mediotiempo import OBS
    o = OBS()
    try:
        if not await asyncio.wait_for(o.conectar(), 5):
            return None
        return await asyncio.wait_for(o.pedir(tipo, datos or {}), 6)
    except Exception as e:  # noqa: BLE001
        log.warning("OBS %s: %s", tipo, e)
        return None
    finally:
        try:
            await o.cerrar()
        except Exception:  # noqa: BLE001
            pass


def modo() -> str:
    return "pausa" if os.path.exists(PAUSA) else "envivo" if os.path.exists(ENVIVO) else "auto"


def programas() -> dict:
    from director.tv.fractal import P
    return {k: {"nombre": v["nombre"], "sub": v["sub"], "color": v.get("color", "#fff"), "tag": v.get("tag", "")} for k, v in P.items()}


def paquete(bid: str) -> str | None:
    from director.tv.productor import ruta_paquete
    try:
        r = ruta_paquete(bid)
        return r if os.path.exists(r) else None
    except Exception:  # noqa: BLE001
        return None


# ───────────────────────── estado ─────────────────────────
async def estado(_r: web.Request) -> web.Response:
    async with aiohttp.ClientSession() as ses:
        chat, chat_msgs, kfp, cer, retro = await asyncio.gather(
            jget(ses, "http://127.0.0.1:8797/estado"), jget(ses, "http://127.0.0.1:8797/chat?after=0"),
            jget(ses, "http://127.0.0.1:8775/estado"), jget(ses, "http://127.0.0.1:8087/health"), jget(ses, RETRO + "/estado.json"))
    st, esc = await asyncio.gather(obs("GetStreamStatus"), obs("GetSceneList"))
    car = leer(F["cartelera"], {}) or {}
    bloques = car.get("bloques", [])
    rel = lambda h: (int(h[:2]) * 60 + int(h[3:5]) - 720) % 1440  # noqa: E731
    ahora_m = rel(time.strftime("%H:%M"))
    for b in bloques:
        a = rel(b["ini"])
        b["estado"] = "pasado" if a + b.get("dura", 40) <= ahora_m else "ahora" if a <= ahora_m else "futuro"
        b["listo"] = bool(paquete(b["id"]))
    try:
        sug = open(os.path.join(LOGS, "chat_para_alice.log"), encoding="utf-8").read().splitlines()[-15:]
    except OSError:
        sug = []
    tend = leer(F["tend"], {}) or {}
    return web.json_response({
        "t": time.strftime("%H:%M:%S"), "modo": modo(),
        "tv": leer(F["estado"], {}), "cartelera": {"jornada": car.get("jornada"), "bloques": bloques},
        "programas": programas(), "consola": leer(F["consola"], {"directriz": "", "temas": {}}), "ahora": leer(F["ahora"], {}),
        "salud": leer(os.path.join(LOGS, "salud.json"), {}), "cerebro": cer,
        "chat": chat, "chat_msgs": ((chat_msgs or {}).get("msgs") or [])[-25:], "sugerencias": sug, "kuroki_fp": kfp,
        "obs": {"stream": bool(st and st.get("outputActive")), "tiempo": (st or {}).get("outputTimecode", ""),
                "escena": (esc or {}).get("currentProgramSceneName"), "escenas": [s["sceneName"] for s in reversed((esc or {}).get("scenes", []))]},
        "retro": retro, "tendencias": {"t": tend.get("t"), "por_programa": {k: [x["termino"] for x in v[:4]] for k, v in (tend.get("por_programa") or {}).items()}},
        "promos": [{"programa": s["programa"], "texto": s["texto"]} for s in ((leer(F["promos"], {}) or {}).get("spots") or [])][:30],
    })


# ───────────────────────── instalaciones ─────────────────────────
async def instalaciones_api(_r: web.Request) -> web.Response:
    from director.tv import instalaciones as I
    from director.tv.fractal import P
    async with aiohttp.ClientSession() as ses:
        est = await jget(ses, ESTUDIO + "/api/estado", 2)
    esc, st = await asyncio.gather(obs("GetCurrentProgramScene"), obs("GetStreamStatus"))
    vivo = bool(est and est.get("set"))
    reales = {x["n"]: x for x in (est or {}).get("sets", [])}
    sets = {}
    for k, v in I.SETS.items():
        pl = (reales.get(k) or {}).get("planos") or v["planos"]
        sets[k] = {**v, "planos": pl, "titulo_real": (reales.get(k) or {}).get("t"),
                   "programas": [{"id": q, "nombre": P[q]["nombre"]} for q in I.RUTAS if k in I.RUTAS[q] and q in P],
                   "miniaturas": {p: f"/sets/{k}__{p}.jpg" for p in pl if os.path.exists(os.path.join(WEB, "sets", f"{k}__{p}.jpg"))}}
    sal = leer(os.path.join(LOGS, "salud.json"), {}) or {}
    return web.json_response({
        "estudio": {"vivo": vivo, "set": (est or {}).get("set"), "plano": (est or {}).get("plano"), "cam": (est or {}).get("cam"), "habla": (est or {}).get("habla")},
        "sets": sets, "anexos": I.ANEXOS, "plantillas": I.PLANTILLAS,
        "obs": {"escena": (esc or {}).get("currentProgramSceneName"), "stream": bool(st and st.get("outputActive"))},
        "cadena": {"director": (sal.get("tv-noche") or {}).get("ok"), "cerebro": (sal.get("cerebro") or {}).get("ok"), "relay": (sal.get("relay") or {}).get("ok"),
                   "salud_t": sal.get("_t")},
        "tv": leer(F["estado"], {}), "modo": modo()})


def mis_programas() -> dict:
    return (leer(MIS, {"programas": {}}) or {"programas": {}}).setdefault("programas", {})


def limpiar_programa(d: dict) -> dict | None:
    """Valida y normaliza lo que manda el navegador (nada se confía)."""
    from director.tv import instalaciones as I
    nombre = str(d.get("nombre") or "").strip()[:60]
    if not nombre:
        return None
    color = d.get("color") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(d.get("color") or "")) else "#ff2fd6"
    tramos = []
    for t in (d.get("tramos") or [])[:30]:
        ls = []
        for l in (t.get("lineas") or [])[:60]:
            q, tx = str(l.get("quien") or "").lower(), str(l.get("texto") or "").strip()[:600]
            if q in ("joy", "kuroki") and tx:
                ls.append({"quien": q, "texto": tx})
        st = t.get("set") if t.get("set") in I.SETS else I.set_inicial({}, "")
        tramos.append({"tema": str(t.get("tema") or "Tramo").strip()[:100], "sub": str(t.get("sub") or "").strip()[:100], "set": st,
                       "cam": re.sub(r"[^a-z0-9_]", "", str(t.get("cam") or "auto").lower()) or "auto", "lineas": ls})
    return {"nombre": nombre.upper(), "sub": str(d.get("sub") or "").strip()[:120], "color": color, "tag": (str(d.get("tag") or "MÍO").strip()[:14] or "MÍO").upper(),
            "set_base": d.get("set_base") if d.get("set_base") in I.SETS else (tramos[0]["set"] if tramos else "panel"), "tramos": tramos}


def segundos(prog: dict) -> int:
    return int(sum(len(l["texto"].split()) / WPS + 1.2 for t in prog["tramos"] for l in t["lineas"]))


async def borrador(d: dict) -> str | list:
    from director.tv import fractal, instalaciones as I
    st = I.SETS.get(d.get("set"), {})
    u = ("Escribe el diálogo de UN tramo de un programa de BlackRose TV entre Joy y Kuroki (nekos cibernéticas conductoras, tono cálido y con humor ligero, "
         "sin inventar datos ni cifras). "
         f"Programa: {str(d.get('programa') or '')[:80]}. Tramo: {str(d.get('tema') or '')[:100]}. Estamos en el set «{st.get('titulo', '')}» ({st.get('que', '')}). "
         f"Indicaciones de la directora: {str(d.get('notas') or 'ninguna')[:300]}. "
         "Son 6 líneas que se alternan, cada una de 1 a 2 frases. Devuelve SOLO JSON: {\"lineas\":[{\"quien\":\"joy\",\"texto\":\"...\"}]}")
    r = await fractal.llm_json(u, 800, 0.8)
    ls = (r.get("lineas") if isinstance(r, dict) else r) or []
    out = [{"quien": str(l.get("quien", "")).lower(), "texto": str(l.get("texto", "")).strip()} for l in ls if isinstance(l, dict)]
    out = [l for l in out if l["quien"] in ("joy", "kuroki") and l["texto"]]
    return out or "El cerebro no devolvió texto (¿está apagado?). Escríbelo tú o enciende el cerebro."


def es_futuro(b: dict) -> bool:
    rel = lambda h: (int(h[:2]) * 60 + int(h[3:5]) - 720) % 1440  # noqa: E731
    return rel(b["ini"]) > rel(time.strftime("%H:%M"))


async def mis_api(_r: web.Request) -> web.Response:
    return web.json_response({"programas": mis_programas()})


# ───────────────────────── acciones ─────────────────────────
async def decir(doll: str, texto: str) -> str:
    async with aiohttp.ClientSession() as s:
        try:
            async with s.post("http://127.0.0.1:8826/api/japon", json={"trad": {"es": texto, "ja": "", "quien": doll.capitalize(), "dur": 3 + len(texto) / 13}},
                              timeout=aiohttp.ClientTimeout(total=3)) as r:
                await r.read()
        except Exception:  # noqa: BLE001
            pass
        try:
            async with s.ws_connect("ws://127.0.0.1:8780/ws", timeout=aiohttp.ClientWSTimeout(ws_close=5)) as ws:
                await ws.send_json({"type": "guion", "doll": doll, "texto": texto, "escena": "hablar"})
            return f"{doll.capitalize()} lo dice"
        except Exception as e:  # noqa: BLE001
            return f"sin voz (director de dolls caído: {e}); solo subtítulo"


async def accion(r: web.Request) -> web.Response:
    d = await r.json()
    a = d.get("accion")
    msg = "ok"
    if a == "modo":
        m = d.get("modo")
        if m == "auto":
            for p in (ENVIVO, PAUSA):
                if os.path.exists(p):
                    os.remove(p)
            sh(os.path.join(RAIZ, "pausa.sh"), "off")
            sh("systemctl", "--user", "start", "llm4b", "tv-noche", "brtv-orquesta", "brtv-chat")
            msg = "AUTO: la TV vuelve a conducir"
        elif m == "envivo":
            open(ENVIVO, "w").close()
            sh("systemctl", "--user", "stop", "tv-noche")
            msg = "EN VIVO: TV apartada, sin cambios de escena; chat y vigilante siguen"
        elif m == "pausa":
            open(PAUSA, "w").close()
            sh("systemctl", "--user", "stop", "tv-noche")
            sh(os.path.join(RAIZ, "pausa.sh"), "on", str(d.get("minutos") or ""))
            msg = "PAUSA: pantalla de pausa; la TV queda detenida hasta «Seguir»"
    elif a == "decir":
        t = str(d.get("texto") or "").strip()[:600]
        msg = await decir(d.get("doll") if d.get("doll") in ("joy", "kuroki") else "kuroki", t) if t else "texto vacío"
    elif a == "id":
        from director.tv import promos
        s = promos.tanda(0)[0]
        msg = await decir(s["quien"], s["texto"])
    elif a == "spot":
        from director.tv import promos
        sp = [x for x in (leer(F["promos"], {}) or {}).get("spots", []) if x["programa"] == d.get("programa")] or promos.tanda(1)[1:]
        s = random.choice(sp)
        msg = await decir(s.get("quien", "joy"), s["texto"])
    elif a == "aviso":
        async with aiohttp.ClientSession() as s:
            body = {"accion": "off"} if d.get("off") else {"minutos": float(d.get("minutos") or 15), "texto": str(d.get("texto") or "")[:140], "con": str(d.get("con") or "")[:60]}
            async with s.post("http://127.0.0.1:8822/api/aviso", json=body) as rr:
                await rr.read()
        msg = "aviso quitado" if d.get("off") else "aviso en pantalla"
    elif a == "escena":
        ok = await obs("SetCurrentProgramScene", {"sceneName": d.get("escena")})
        msg = f"escena «{d.get('escena')}»" + ("" if ok is not None else " (OBS no respondió)")
        if modo() == "auto":
            msg += " · ojo: en AUTO el director de TV puede cambiarla en el próximo tramo (usa EN VIVO para fijarla)"
    elif a == "ahora":
        escribir(F["ahora"], {"texto": str(d.get("texto") or "")[:300], "juego": str(d.get("juego") or "")[:60]})
        msg = "contexto actualizado (chat y Kuroki)" if d.get("texto") else "contexto borrado"
    elif a == "retro":
        j = d.get("juego")
        async with aiohttp.ClientSession() as s:
            if j in ("goldeneye", "f1", "pes", "aero"):
                q = f"juego={j}" + (f"&dato={urllib.parse.quote(d['dato'])}" if d.get("dato") else "")
                await jget(s, f"{RETRO}/set?{q}")
        p = os.path.expanduser("~/overlays_retro/estado.json")
        e = leer(p, {}) or {}
        e["activo"] = j in ("goldeneye", "f1", "pes", "aero")
        escribir(p, e)
        msg = f"juego retro: {j}" if e["activo"] else "modo retro apagado"
    elif a == "directriz":
        c = leer(F["consola"], {"directriz": "", "temas": {}}) or {}
        c["directriz"] = str(d.get("texto") or "")[:500]
        escribir(F["consola"], c)
        msg = "directriz guardada: entra en todo lo que se escriba desde ahora"
    elif a == "tema":
        c = leer(F["consola"], {"directriz": "", "temas": {}}) or {}
        pid, t = d.get("programa"), str(d.get("tema") or "").strip()[:140]
        if pid in programas() and t:
            c.setdefault("temas", {}).setdefault(pid, [])
            if d.get("quitar"):
                c["temas"][pid] = [x for x in c["temas"][pid] if x != t]
            elif t not in c["temas"][pid]:
                c["temas"][pid].append(t)
            escribir(F["consola"], c)
            msg = "tema quitado" if d.get("quitar") else f"tema agregado a {programas()[pid]['nombre']}: sale en el próximo episodio"
        else:
            msg = "falta programa o tema"
    elif a == "reprogramar":
        car = leer(F["cartelera"], {}) or {}
        pid = d.get("programa")
        from director.tv.fractal import P
        for b in car.get("bloques", []):
            if b["id"] == d.get("bloque") and pid in P:
                v = P[pid]
                b.update(programa=pid, nombre=v["nombre"], sub=v["sub"], color=v.get("color", b.get("color")), tag=v.get("tag", b.get("tag")), fractal=True)
                pq = paquete(b["id"])
                if pq:
                    os.replace(pq, pq + ".reprogramado")
                escribir(F["cartelera"], car)
                msg = f"{b['ini']} ahora es {v['nombre']}: el productor lo arma"
                break
        else:
            msg = "bloque no encontrado (o programa inválido)"
    elif a == "producir":
        pq = paquete(d.get("bloque", ""))
        if pq:
            os.replace(pq, pq + ".rehacer")
        msg = "el productor lo vuelve a armar en su próxima vuelta (≤45 s)"
    elif a == "promos":
        from director.tv import promos
        asyncio.create_task(promos.producir())
        msg = "tanda de spots nueva en camino (1 llamada)"
    elif a == "tendencias":
        from director.tv import tendencias
        await asyncio.to_thread(tendencias.actualizar)
        msg = "tendencias actualizadas"
    elif a == "stream":
        if d.get("que") == "reiniciar":
            await obs("StopStream")
            await asyncio.sleep(6)
            await obs("StartStream")
            msg = "transmisión reiniciada"
        elif d.get("que") == "iniciar":
            await obs("StartStream")
            msg = "transmitiendo"
    elif a in ("estudio_set", "estudio_cam"):
        from director.tv import instalaciones as I
        n = str(d.get("n") or "")
        if a == "estudio_set" and n not in I.SETS:
            msg = "set desconocido"
        else:
            async with aiohttp.ClientSession() as s:
                r_ = await jget(s, f"{ESTUDIO}/api/{'set' if a == 'estudio_set' else 'cam'}?n={urllib.parse.quote(re.sub(r'[^a-z0-9_]', '', n.lower()))}", 3)
            msg = (f"estudio → {n}" if r_ is not None else "el estudio Unity no responde (¿está encendido?)")
            if r_ is not None and modo() == "auto":
                msg += " · en AUTO el director cambia de set en el próximo tema"
    elif a == "estudio_encender":
        from director.tv import instalaciones as I
        s_ = d.get("set") if d.get("set") in I.SETS else "noticiario"
        if os.path.exists(AIRE):
            subprocess.Popen([AIRE, s_], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg = f"encendiendo el estudio en «{s_}» (tarda ~30 s; usa la RTX no, la AMD; ojo con la RAM)"
        else:
            msg = "no encuentro ~/BlackroseTV_build/aire.sh"
    elif a == "estudio_apagar":
        msg = sh(AIRE, "stop") or "estudio apagado"
    elif a == "mi_guardar":
        prog = limpiar_programa(d.get("programa") or {})
        if not prog:
            msg = "ponle un nombre al programa"
        else:
            slug = re.sub(r"[^a-z0-9]", "", str(d.get("slug") or "").lower())[:24] or re.sub(r"[^a-z0-9]", "", prog["nombre"].lower())[:16] or f"p{int(time.time())}"
            todo = leer(MIS, {"programas": {}}) or {"programas": {}}
            todo.setdefault("programas", {})[slug] = prog
            escribir(MIS, todo)
            return web.json_response({"ok": True, "msg": f"guardado «{prog['nombre']}» · ~{segundos(prog) // 60} min de texto", "slug": slug})
    elif a == "mi_borrar":
        todo = leer(MIS, {"programas": {}}) or {"programas": {}}
        if todo.get("programas", {}).pop(str(d.get("slug")), None) is not None:
            escribir(MIS, todo)
            msg = "programa borrado (si ya estaba en la cartelera, ahí se queda)"
        else:
            msg = "no existe"
    elif a == "mi_borrador":
        r_ = await borrador(d)
        return web.json_response({"ok": isinstance(r_, list), "msg": "borrador listo: revísalo y edítalo" if isinstance(r_, list) else r_, "lineas": r_ if isinstance(r_, list) else []})
    elif a == "mi_programar":
        prog = mis_programas().get(str(d.get("slug")))
        car = leer(F["cartelera"], {}) or {}
        b = next((x for x in car.get("bloques", []) if x["id"] == d.get("bloque")), None)
        if not prog:
            msg = "guarda el programa primero"
        elif not b or b.get("especial") or not es_futuro(b):
            msg = "elige un bloque futuro de la cartelera (no uno ya emitido ni un especial)"
        elif not any(t["lineas"] for t in prog["tramos"]):
            msg = "el programa no tiene líneas todavía: escribe o pide un borrador"
        else:
            slug = str(d["slug"])
            nid = f"mio-{slug}_{b['ini'].replace(':', '')}"
            vieja = paquete(b["id"])
            if vieja:
                os.replace(vieja, vieja + ".reprogramado")
            b.update(id=nid, programa=f"mio-{slug}", nombre=prog["nombre"], sub=prog["sub"], color=prog["color"], tag=prog["tag"], fractal=False, manual=True, set_base=prog["set_base"])
            from director.tv.productor import ruta_paquete
            items = [{"tipo": "charla", "tema": t["tema"], "sub": t["sub"] or prog["sub"], "set": t["set"], "cam": t["cam"], "lineas": t["lineas"]} for t in prog["tramos"] if t["lineas"]]
            escribir(ruta_paquete(nid), {"bloque": nid, "programa": b["programa"], "fecha": car.get("jornada"), "creado": time.strftime("%H:%M:%S"), "fractal": False, "manual": True,
                                         "items": items, "estado": {"episodios": 1, "temas": len(items), "seg_charla": segundos(prog), "medios": 0}})
            escribir(F["cartelera"], car)
            falta = b.get("dura", 40) * 60 - segundos(prog)
            msg = f"{b['ini']} ahora es «{prog['nombre']}» ({len(items)} tramos, ~{segundos(prog) // 60} min de texto)" + \
                  (f" · sobran ~{falta // 60} min: se rellenan con radio" if falta > 120 else f" · faltan ~{-falta // 60} min: el cierre llega antes de que terminen los últimos tramos" if falta < -120 else "")
    else:
        msg = f"acción desconocida: {a}"
    log.info("acción %s → %s", a, msg)
    return web.json_response({"ok": True, "msg": msg})


def app() -> web.Application:
    a = web.Application()
    a.router.add_get("/api/estado", estado)
    a.router.add_post("/api/accion", accion)
    a.router.add_get("/api/instalaciones", instalaciones_api)
    a.router.add_get("/api/mis_programas", mis_api)
    a.router.add_static("/sets/", os.path.join(WEB, "sets"))
    a.router.add_get("/", lambda _r: web.FileResponse(os.path.join(WEB, "index.html")))
    return a


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    web.run_app(app(), host="127.0.0.1", port=PUERTO, print=lambda *_: log.info("consola del canal en http://127.0.0.1:%d", PUERTO))
