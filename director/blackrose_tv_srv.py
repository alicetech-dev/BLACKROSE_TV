"""BlackRose TV, servidor propio del overlay (:8822): logo, relojes y marquesina de acciones tech + criptos.

Va APARTE del director y de las dolls: si las apagás (o se cae el director), la barra y el logo siguen andando y solo
se esconden «Ahora» y el titular. Lo del programa lo pide al director (:8780/api/programa) con timeout corto.
  .venv/bin/python -m director.blackrose_tv_srv [--puerto 8822]     (servicio: systemctl --user … blackrose-tv)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import logging
import os
import time

import aiohttp
from aiohttp import web

from .programacion import Mercados

HERE = os.path.dirname(os.path.abspath(__file__))
DIRECTOR = os.environ.get("BRTV_DIRECTOR", "http://127.0.0.1:8780")
ESTADO = os.path.join(os.path.dirname(HERE), "logs", "brtv_overlay.json")   # aviso + última transición (sobrevive al reinicio)
TRANSICIONES = ("ident", "ultima_hora", "volvemos", "mercados", "corte", "senal",
                "spot_noticias", "spot_documental", "spot_gamer", "spot_ciencia", "spot_conductoras")
APAGADO = {"activo": False, "bloque": None, "noticia": None, "siguiente": None, "paso": "sin director"}


async def leer_twitch(canal: str, chat: list) -> None:
    """Chat de Twitch en anónimo (justinfan) para la caja del overlay: no depende del director ni de las dolls."""
    import random
    import re
    from websockets.asyncio.client import connect
    while True:
        try:
            async with connect("wss://irc-ws.chat.twitch.tv:443", open_timeout=10) as ws:
                await ws.send("CAP REQ :twitch.tv/tags")
                await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
                await ws.send(f"JOIN #{canal}")
                async for crudo in ws:
                    for ln in str(crudo).split("\r\n"):
                        if ln.startswith("PING"):
                            await ws.send("PONG" + ln[4:])
                            continue
                        m = re.match(r"(?:@(\S+) )?:(\w+)!\S+ PRIVMSG #\w+ :(.*)", ln)
                        if not m:
                            continue
                        tags = dict(t.split("=", 1) for t in (m.group(1) or "").split(";") if "=" in t)
                        chat.append({"id": tags.get("id") or str(time.time()), "autor": tags.get("display-name") or m.group(2),
                                     "color": tags.get("color") or "", "texto": m.group(3)[:300], "t": time.time()})
                        del chat[:-40]
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001  (se reconecta sola)
            logging.warning("chat twitch: %s; reintento en 10 s", e)
        await asyncio.sleep(10)


def app() -> web.Application:
    m = Mercados()
    chat: list = []
    a = web.Application(client_max_size=80 * 1024 ** 2)  # capturas de pantalla: varias de unos MB
    sesion: dict = {}
    est: dict = {"aviso": {"activo": False}, "trans": {"id": 0, "tipo": "", "t": 0}}
    try:
        est.update(json.load(open(ESTADO)))
    except (OSError, ValueError):
        pass

    def guardar():
        try:
            json.dump(est, open(ESTADO, "w"))
        except OSError:
            pass

    async def api_pausa(r):
        """GET = estado · POST {"minutos":15} = «volvemos en 15:00» en la pausa comercial · {"accion":"off"} = «volvemos pronto»."""
        if r.method == "POST":
            try:
                d = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            if d.get("accion") == "off" or not d.get("minutos"):
                est["pausa"] = {"activo": False}
            else:
                est["pausa"] = {"activo": True, "hasta": time.time() + float(d["minutos"]) * 60}
            guardar()
        return web.json_response(est.get("pausa") or {"activo": False}, headers={"Cache-Control": "no-store"})

    METAS = os.path.join(os.path.dirname(HERE), "director", "metas.json")

    tv_est = {"modo": "idle", "id": 0}

    async def api_tv(r):
        """Pantalla del canal nocturno (web/tv/index.html). GET = estado · POST = lo fija el director de TV: {"modo":"idle|charla|video|musica|corte|cierre", ...} (cada POST sube `id`)."""
        if r.method == "POST":
            try:
                x = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            n = tv_est.get("id", 0) + 1
            tv_est.clear()
            tv_est.update(x)
            tv_est["id"] = n
            tv_est["t"] = time.time()
        return web.json_response({**tv_est, "ahora": time.time()}, headers={"Cache-Control": "no-store"})

    capa_est: dict = {"id": 0}

    async def api_capa(r):
        """Capa del estudio (web/capa/index.html, 20-nov): zocalo, quien, visual {img, credito}, diagrama, cta {redes, texto, seg}, cama (volumen de la música de fondo).
        POST une campos (null borra); cada POST sube `id`."""
        if r.method == "POST":
            try:
                x = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            for k, v in (x or {}).items():
                if v is None:
                    capa_est.pop(k, None)
                else:
                    capa_est[k] = v
                if k == "cta" and v:
                    capa_est["cta"] = {**v, "hasta": time.time() + float(v.get("seg", 25))}
            capa_est["id"] = capa_est.get("id", 0) + 1
        return web.json_response({**capa_est, "ahora": time.time()}, headers={"Cache-Control": "no-store"})

    async def api_cama(r):
        """Lista de temas de la RADIO 2049 para la cama musical de la capa (al azar)."""
        try:
            from director.tv.radio import temas
        except ImportError:
            from tv.radio import temas
        ts = [{"src": "/tv/media/" + t["audio"], "titulo": t["titulo"], "atribucion": t["atribucion"], "genero": t["genero"]} for t in temas(["phonk", "techno", "darktechno", "darksynth", "synthwave", "citypop", "cyberpunk", "coding"])]
        random.shuffle(ts)
        return web.json_response(ts[:40], headers={"Cache-Control": "no-store"})

    cartelera_est = {"mostrar_hasta": 0}

    async def api_cartelera(r):
        """GET = cartelera de la noche (director/tv/cartelera.json, editable en vivo) + mostrar_hasta · POST {"mostrar":25} saca la tarjeta grande N s."""
        try:
            d = json.load(open(os.path.join(HERE, "tv", "cartelera.json"), encoding="utf-8"))
        except (OSError, ValueError):
            d = {"bloques": []}
        if r.method == "POST":
            try:
                x = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            if "mostrar" in x:
                cartelera_est["mostrar_hasta"] = time.time() + float(x["mostrar"])
        d["mostrar_hasta"] = cartelera_est["mostrar_hasta"]
        d["ahora"] = time.time()
        return web.json_response(d, headers={"Cache-Control": "no-store"})

    async def api_metas(r):
        """GET = metas de suscriptores (director/metas.json) · POST {"actual":42} | {"sumar":1} | {"max":..,"etiqueta":..,"hitos":[{"en":50,"premio":"…"}]}."""
        try:
            d = json.load(open(METAS, encoding="utf-8"))
        except (OSError, ValueError):
            d = {"etiqueta": "SUSCRIPTORES", "actual": 0, "max": 100, "hitos": []}
        if r.method == "POST":
            try:
                x = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            if "sumar" in x:
                d["actual"] = int(d.get("actual", 0)) + int(x["sumar"])
            for k in ("actual", "max", "etiqueta", "hitos"):
                if k in x and k != "sumar":
                    d[k] = x[k]
            d["actual"] = max(0, min(int(d.get("max", 100)), int(d.get("actual", 0))))
            json.dump(d, open(METAS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return web.json_response(d, headers={"Cache-Control": "no-store"})

    from .mediotiempo import MedioTiempo
    mt = MedioTiempo()

    async def api_mediotiempo(r):
        """GET = estado del show de medio tiempo · POST {"accion":"iniciar"|"parar","obs":true,"desde":"A"|"B"}."""
        if r.method == "POST":
            try:
                d = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            if d.get("accion") == "iniciar":
                res = await mt.iniciar(obs=bool(d.get("obs", True)), desde=str(d.get("desde") or "A").upper())
            elif d.get("accion") == "parar":
                res = await mt.parar()
            else:
                return web.json_response({"ok": False, "error": "accion: iniciar | parar"}, status=400)
            return web.json_response({**res, **mt.estado()})
        return web.json_response(mt.estado(), headers={"Cache-Control": "no-store"})

    from .show_kuroki import ShowKuroki
    sk = ShowKuroki(mt)

    async def api_showkuroki(r):
        """GET = estado del Show de Kuroki · POST {"accion":"iniciar","tanda":true,"obs":true} | {"accion":"parar"}."""
        if r.method == "POST":
            try:
                d = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            if d.get("accion") == "iniciar":
                res = await sk.iniciar(tanda=bool(d.get("tanda", True)), obs=bool(d.get("obs", True)))
            elif d.get("accion") == "parar":
                res = await sk.parar()
            else:
                return web.json_response({"ok": False, "error": "accion: iniciar | parar"}, status=400)
            return web.json_response({**res, **sk.estado()})
        return web.json_response(sk.estado(), headers={"Cache-Control": "no-store"})

    seg: dict = {"activo": False}

    async def api_segmento(r):
        """Estado del INFORME ESPECIAL (lo empuja el director al narrar): POST {"activo":true,"i":2,"n":11,"slide":{…},"quien":"joy"} · {"activo":false}."""
        if r.method == "POST":
            try:
                seg.clear(); seg.update(await r.json())
            except ValueError:
                return web.json_response({"ok": False}, status=400)
        return web.json_response(seg, headers={"Cache-Control": "no-store"})

    async def api_fp(_r):
        """Código de party y rango de Fast Penguin (estado.json de ~/overlays_fastpenguin), para los spots."""
        try:
            e = json.load(open(os.path.expanduser("~/overlays_fastpenguin/estado.json")))
        except (OSError, ValueError):
            e = {}
        return web.json_response({k: e.get(k) for k in ("party", "rango", "pts", "nick")}, headers={"Cache-Control": "no-store"})

    def aviso_vigente() -> dict:
        av = est["aviso"]
        if av.get("activo") and time.time() > float(av.get("hasta", 0)) + 90:   # 90 s de «ya vuelvo» y se apaga solo
            av["activo"] = False
            guardar()
        return av

    async def api_aviso(r):
        """GET = estado · POST {"minutos":15,"con":"Fast Penguin"} (o "texto" libre) = pone el aviso · {"accion":"off"} = lo quita."""
        if r.method == "POST":
            try:
                d = await r.json()
            except ValueError:
                return web.json_response({"ok": False, "error": "JSON"}, status=400)
            if d.get("accion") == "off" or d.get("activo") is False:
                est["aviso"] = {"activo": False}
            else:
                mins = float(d.get("minutos", 15))
                est["aviso"] = {"activo": True, "hasta": time.time() + mins * 60, "minutos": mins,
                                "con": str(d.get("con") or "Fast Penguin")[:60], "texto": str(d.get("texto") or "")[:140],
                                "quien": str(d.get("quien") or "BLACKROSE")[:30]}
            guardar()
        return web.json_response({"ok": True, **aviso_vigente()}, headers={"Cache-Control": "no-store"})

    async def api_transicion(r):
        """POST {"tipo":"ident"} (o GET ?tipo=ident) = dispara esa transición en el overlay, con o sin programa."""
        tipo = r.query.get("tipo", "")
        if r.method == "POST":
            try:
                tipo = (await r.json()).get("tipo", tipo)
            except ValueError:
                pass
        if tipo not in TRANSICIONES:
            return web.json_response({"ok": False, "error": "tipo: " + " | ".join(TRANSICIONES)}, status=400)
        est["trans"] = {"id": est["trans"]["id"] + 1, "tipo": tipo, "t": time.time()}
        guardar()
        return web.json_response({"ok": True, **est["trans"]})

    async def programa(_r):
        try:
            s = sesion.get("s") or sesion.setdefault("s", aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1.5)))
            async with s.get(DIRECTOR + "/api/programa") as r:
                d = await r.json(content_type=None)
        except Exception:  # noqa: BLE001  (director apagado o colgado: el overlay esconde solo lo del programa)
            d = APAGADO
        d = {**d, "aviso": aviso_vigente(), "trans": est["trans"]}   # lo propio de este servidor, en el mismo sondeo
        return web.json_response(d, headers={"Cache-Control": "no-store"})

    async def arrancar(_a):
        asyncio.create_task(m.loop())
        asyncio.create_task(leer_twitch(os.environ.get("BRTV_TWITCH", "barbieblackrose"), chat))

    async def cerrar(_a):
        if sesion.get("s"):
            await sesion["s"].close()

    a.on_startup.append(arrancar)
    a.on_cleanup.append(cerrar)
    a.router.add_get("/api/programa", programa)
    a.router.add_get("/api/chat", lambda r: web.json_response(chat[-12:], headers={"Cache-Control": "no-store"}))

    # 📰 redacción: Blackrose sube capturas + recorte + artículo; Grok arma la ficha; la programación la emite
    from . import redaccion as R

    async def api_redaccion(r):
        if r.method == "GET":
            return web.json_response(R.listar(), headers={"Cache-Control": "no-store"})
        form = await r.post()
        imgs, recorte = [], None
        for k, v in form.items():
            if hasattr(v, "file"):
                datos = v.file.read()
                if not datos:
                    continue
                if k == "recorte" and recorte is None:
                    recorte = datos
                else:
                    imgs.append(datos)
        texto = str(form.get("texto") or "").strip()
        if not imgs and not recorte and not texto:
            return web.json_response({"ok": False, "error": "deja al menos una imagen o pega un texto/link"}, status=400)
        try:
            n = R.crear(imgs, recorte, texto, str(form.get("titulo") or ""), str(form.get("fuente") or ""),
                        str(form.get("bloque") or "auto"))
        except Exception as e:  # noqa: BLE001  (imagen que PIL no abre, disco lleno…)
            return web.json_response({"ok": False, "error": f"no pude guardar: {e}"}, status=400)
        asyncio.create_task(R.procesar(n["id"]))
        return web.json_response({"ok": True, "id": n["id"]})

    async def api_nota(r):
        id_ = r.match_info["id"]
        if r.method == "DELETE":
            return web.json_response({"ok": R.borrar(id_)})
        d = await r.json() if r.can_read_body else {}
        if d.get("accion") == "reintentar":
            R.marcar(id_, "procesando", error="")
            asyncio.create_task(R.procesar(id_))
        elif d.get("accion") == "bloque":
            R.marcar(id_, (R.leer(id_) or {}).get("estado", "lista"), bloque=str(d.get("bloque") or "auto"))
        elif d.get("accion") == "primera":  # al frente de la fila
            R.marcar(id_, (R.leer(id_) or {}).get("estado", "lista"), orden=0)
        return web.json_response({"ok": True, **(R.leer(id_) or {})})

    async def img_nota(r):
        f = R.RAIZ / r.match_info["id"] / r.match_info["nombre"]
        if not f.is_file() or ".." in r.match_info["nombre"]:
            raise web.HTTPNotFound()
        return web.FileResponse(f, headers={"Cache-Control": "max-age=3600"})

    a.router.add_route("*", "/api/redaccion", api_redaccion)
    a.router.add_route("*", "/api/redaccion/{id}", api_nota)
    a.router.add_get("/redaccion/img/{id}/{nombre}", img_nota)
    a.router.add_get("/redaccion", lambda r: web.FileResponse(os.path.join(HERE, "web", "redaccion.html"),
                                                              headers={"Cache-Control": "no-store"}))
    a.router.add_route("*", "/api/pausa", api_pausa)
    a.router.add_get("/api/fp", api_fp)
    a.router.add_route("*", "/api/metas", api_metas)
    a.router.add_route("*", "/api/cartelera", api_cartelera)
    a.router.add_route("*", "/api/tv", api_tv)
    a.router.add_route("*", "/api/capa", api_capa)
    a.router.add_get("/api/cama", api_cama)
    a.router.add_get("/capa", lambda r: web.HTTPFound("/capa/"))
    a.router.add_get("/capa/", lambda r: web.FileResponse(os.path.join(HERE, "web", "capa", "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_static("/capa/", os.path.join(HERE, "web", "capa"))
    a.router.add_static("/medios/", os.path.join(HERE, "tv", "medios"))
    a.router.add_get("/tv", lambda r: web.HTTPFound("/tv/"))
    a.router.add_get("/tv/", lambda r: web.FileResponse(os.path.join(HERE, "web", "tv", "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_static("/tv/", os.path.join(HERE, "web", "tv"))
    a.router.add_get("/cartelera", lambda r: web.HTTPFound("/cartelera/"))
    a.router.add_get("/cartelera/", lambda r: web.FileResponse(os.path.join(HERE, "web", "cartelera", "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_route("*", "/api/segmento", api_segmento)
    a.router.add_route("*", "/api/mediotiempo", api_mediotiempo)
    a.router.add_route("*", "/api/showkuroki", api_showkuroki)
    a.router.add_get("/showkuroki", lambda r: web.HTTPFound("/showkuroki/"))
    a.router.add_get("/showkuroki/", lambda r: web.FileResponse(os.path.join(HERE, "web", "showkuroki", "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_static("/showkuroki/", os.path.join(HERE, "web", "showkuroki"))
    a.router.add_get("/mediotiempo", lambda r: web.HTTPFound("/mediotiempo/"))
    a.router.add_get("/mediotiempo/", lambda r: web.FileResponse(os.path.join(HERE, "web", "mediotiempo", "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_static("/mediotiempo/", os.path.join(HERE, "web", "mediotiempo"))
    for _d in ("senal", "cierre", "ajuste"):    # pantallas de transición «mejorando señal» y cortina de cierre
        a.router.add_get(f"/{_d}/", lambda r, _d=_d: web.FileResponse(os.path.join(HERE, "web", _d, "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_get("/ajuste/guion.json", lambda r: web.FileResponse(os.path.join(HERE, "web", "ajuste", "guion.json"), headers={"Cache-Control": "no-store"}))
    a.router.add_get("/segmento", lambda r: web.HTTPFound("/segmento/"))
    a.router.add_get("/segmento/", lambda r: web.FileResponse(os.path.join(HERE, "web", "segmento", "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_static("/segmento/", os.path.join(HERE, "web", "segmento"))
    a.router.add_get("/metas", lambda r: web.FileResponse(os.path.join(HERE, "web", "metas.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_get("/pausa", lambda r: web.HTTPFound("/pausa/"))
    a.router.add_get("/pausa/", lambda r: web.FileResponse(os.path.join(HERE, "web", "pausa", "index.html"), headers={"Cache-Control": "no-store"}))
    a.router.add_static("/pausa/", os.path.join(HERE, "web", "pausa"))
    a.router.add_route("*", "/api/aviso", api_aviso)
    a.router.add_route("*", "/api/transicion", api_transicion)
    a.router.add_get("/api/mercados", lambda r: web.json_response(m.datos, headers={"Cache-Control": "no-store"}))
    pagina = lambda r: web.FileResponse(os.path.join(HERE, "web", "blackrose_tv.html"),  # noqa: E731
                                        headers={"Cache-Control": "no-store"})
    a.router.add_get("/transiciones", lambda r: web.FileResponse(os.path.join(HERE, "web", "blackrose_tv_transiciones.html"),
                                                                 headers={"Cache-Control": "no-store"}))
    a.router.add_get("/", pagina)
    a.router.add_get("/blackrose_tv", pagina)
    a.router.add_static("/img", os.path.join(HERE, "web", "img"))
    return a


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puerto", type=int, default=8822)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    web.run_app(app(), host="127.0.0.1", port=args.puerto, print=None, access_log=None)


if __name__ == "__main__":
    main()
