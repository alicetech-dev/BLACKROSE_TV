"""BlackRose TV: parrilla de programación para las dolls (ver director/programacion.yaml, el guion).

Rota bloques (Tecnología, Noticias Gamer, IA, Contingencia internacional). Cada bloque trae titulares reales de Google
News (RSS, sin clave), y por cada noticia arma una mini charla en pasos (presenta → analiza → matiza → pregunta al
chat). Usa los mismos pasos que `Web.conversar` (prioridad 2): el chat de Twitch/Discord (prioridad 1) se mete entre
turno y turno, y la sala autónoma se calla mientras haya programa (conv activa). El estado lo lee el overlay
/blackrose_tv por GET /api/programa.
"""
from __future__ import annotations

import asyncio
import email.utils
import html
import json
import logging
import random
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import aiohttp
import yaml

log = logging.getLogger("director.programacion")
VISTOS = Path(__file__).resolve().parent.parent / "logs" / "programacion_vistos.json"


class Programacion:
    def __init__(self, web, archivo: str, activo: bool = True):
        self.w = web
        self.archivo = archivo
        self.g = yaml.safe_load(open(archivo, encoding="utf-8"))
        self.bloques = self.g["bloques"]
        self.activo = activo
        self.solo: str | None = self.g.get("solo") or None  # doll que conduce SOLA (None = presenta + comenta)
        self._cuna_n = 0
        self.segmento: str | None = None
        self._seg_stop = False
        self.lang: str = str(self.g.get("idioma", "es") or "es")  # idioma del programa: es | ja | en (en vivo: accion «idioma»)
        self._fijo: str | None = None  # bloque que se repite sin avanzar (ej. fastpenguin mientras ella juega)
        self._act: dict | None = None  # bloque en curso
        self.i = 0  # bloque actual
        self.estado: dict = {"activo": activo, "bloque": None, "noticia": None, "siguiente": None, "paso": "",
                             "cuna": None, "solo": self.solo, "idioma": self.lang}
        self._saltar = False  # «siguiente»: corta la noticia en curso
        self._ir_a: str | None = None  # «bloque»: salta a ese bloque al terminar el paso
        self._bloques_hechos = 0
        try:
            self.vistos: list[str] = json.loads(VISTOS.read_text())
        except (OSError, ValueError):
            self.vistos = []

    # --- noticias ------------------------------------------------------------------------
    def _url(self, consulta: str) -> str:
        p = self.g.get("google_news", "hl=es-419&gl=CL&ceid=CL:es-419")
        if consulta.startswith("@topic:"):
            return f"https://news.google.com/rss/headlines/section/topic/{consulta[7:]}?{p}"
        return f"https://news.google.com/rss/search?q={urllib.parse.quote(consulta)}&{p}"

    async def _titulares(self, consulta: str) -> list[dict]:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
                async with s.get(self._url(consulta), headers={"User-Agent": "Mozilla/5.0"}) as r:
                    xml = await r.text()
            raiz = ET.fromstring(xml)
        except Exception as e:  # noqa: BLE001  (sin red: el bloque usa sus temas de respaldo)
            log.warning("noticias «%s»: %s", consulta, e)
            return []
        tope = float(self.g.get("noticias_max_horas", 36)) * 3600
        out = []
        for it in raiz.iter("item"):
            fuente = (it.findtext("source") or "").strip()
            titulo = (it.findtext("title") or "").strip()
            if fuente and titulo.endswith(" - " + fuente):
                titulo = titulo[: -len(fuente) - 3].strip()
            try:
                t = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
            except (TypeError, ValueError):
                t = time.time()
            if time.time() - t > tope or len(titulo) < 25:
                continue
            # la descripción de Google News trae la cobertura de otros medios: contexto barato para no inventar
            desc = html.unescape(it.findtext("description") or "")
            rel = [html.unescape(re.sub(r"<[^>]+>", "", a)).strip() for a in re.findall(r"<a [^>]*>(.*?)</a>", desc)]
            rel = [x for x in rel if x and x != titulo][:3]
            out.append({"titulo": titulo, "fuente": fuente or "Google News", "t": t, "relacionadas": rel})
        return out

    def _clave(self, titulo: str) -> str:
        return re.sub(r"\W+", " ", titulo.lower()).strip()[:80]

    VACIAS = set("para como pero sobre entre desde hasta tras ante contra según este esta estos estas cuál cuando donde "
                 "porque también más menos muy todo toda todos todas nuevo nueva hace tiene puede sus los las una unos "
                 "unas del con por que qué the and for with from".split())

    def _palabras(self, t: str) -> set[str]:
        return {w for w in re.findall(r"\w{4,}", t.lower()) if w not in self.VACIAS}

    def _parecido(self, a: str, b: str) -> bool:
        """Misma historia con otro titular (p. ej. tres medios con el acuerdo OpenAI-Chile): comparten casi todo."""
        pa, pb = self._palabras(a), self._palabras(b)
        if not (pa and pb):
            return False
        comunes = pa & pb
        propios = {w.lower() for w in re.findall(r"(?<!^)(?<![.:¿¡«\"“] )\b[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]{2,}", a + " | " + b)}
        return len(comunes) / min(len(pa), len(pb)) >= 0.34 or (len(comunes) >= 2 and bool(comunes & propios))

    async def noticias(self, b: dict) -> list[dict]:
        """Hasta `noticias` titulares nuevos: ni vistos antes ni la misma historia contada por otro medio."""
        n, out, medios = int(b.get("noticias", 3)), [], set()
        recientes = self.vistos[-80:]
        tope_c = int(b.get("por_consulta", 0) or 0)  # >0: a lo más N titulares por consulta (varios temas, no uno solo)
        for c in b.get("consultas") or []:
            de_esta = 0
            for x in await self._titulares(c):
                if tope_c and de_esta >= tope_c:
                    break
                k = self._clave(x["titulo"])
                if (k in self.vistos or any(self._parecido(x["titulo"], o["titulo"]) for o in out)
                        or any(self._parecido(x["titulo"], v) for v in recientes)):
                    continue
                if x["fuente"] in medios and len(out) < n - 1:
                    continue
                out.append(x)
                de_esta += 1
                medios.add(x["fuente"])
                if len(out) >= n:
                    return out
        return out

    def _marcar_vista(self, titulo: str) -> None:
        self.vistos = (self.vistos + [self._clave(titulo)])[-600:]
        try:
            VISTOS.parent.mkdir(parents=True, exist_ok=True)
            VISTOS.write_text(json.dumps(self.vistos, ensure_ascii=False))
        except OSError:
            pass

    # --- el programa ---------------------------------------------------------------------
    def _publico(self, b: dict | None) -> dict | None:
        return b and {k: b.get(k) for k in ("id", "nombre", "sub", "color", "icono")}

    def _emitir(self, **cambios) -> None:
        self.estado.update(cambios, activo=self.activo, t=time.time())
        self.w.emitir({"type": "programa", **self.estado})

    def _tema(self, b: dict, nota: dict | None, instr: str, otra: str) -> str:
        if nota and nota.get("ficha"):  # noticia que trajo Blackrose a la redacción: hay ficha completa
            f = nota["ficha"]
            datos = " · ".join(str(x) for x in (f.get("datos") or [])[:6])
            hecho = (f"NOTICIA EXCLUSIVA que Blackrose trajo a la redacción: «{nota['titulo']}» ({nota['fuente']}"
                     + (f", {f['fecha']}" if f.get("fecha") else "") + f"). RESUMEN: {f.get('resumen', '')} "
                     + (f"DATOS CONCRETOS (úsalos tal cual): {datos}. " if datos else "")
                     + (f"CONTEXTO: {f['contexto']} " if f.get("contexto") else "")
                     + (f"ÁNGULO PARA DEBATIR: {f['angulo']} " if f.get("angulo") else "")
                     + "Las capturas de la noticia están en pantalla: puedes decir «como ven en pantalla». "
                     "Aquí SÍ conoces el artículo: da detalles concretos, sin inventar nada fuera de la ficha.")
        elif nota:
            hace = max(1, round((time.time() - nota["t"]) / 3600))
            rel = ("; ".join(f"«{r}»" for r in nota["relacionadas"]))
            hecho = (f"NOTICIA: «{nota['titulo']}» ({nota['fuente']}, hace ~{hace} h)."
                     + (f" Otros medios: {rel}." if rel else ""))
        else:
            hecho = "No hay titulares nuevos: charlen sobre este tema de fondo, sin presentarlo como noticia de hoy."
        return (f"BlackRose TV, bloque {b['nombre']}. {hecho} TONO: {b.get('tono', '')} "
                f"TU PARTE AHORA: {instr.format(otra=otra)} REGLAS: {self.g.get('reglas_' + self.lang) or self.g.get('reglas', '')}")

    def _solo(self) -> str | None:
        """La conductora única, salvo en bloques con `ambas: true` (conducen las dos)."""
        if self._act and self._act.get("ambas"):
            return None
        return self.solo if self.solo in self.w.dolls else None

    def _puede(self) -> bool:
        w = self.w
        if self._solo():  # una sola conductora: basta con que ella esté libre y despierta
            r = w.dolls[self._solo()]
            return self.activo and not w.silencio and not r.estado.titere and not r.estado.dormida
        return (self.activo and not w.silencio and len(w.libres()) >= 2
                and not any(r.estado.dormida for r in w.dolls.values()))

    async def _esperar_turno(self) -> bool:
        """Espera a que nadie hable, no haya chat en fila ni otra conversación (la de la consola manda)."""
        w = self.w
        while True:
            if not self.activo:
                return False
            if (self._puede() and not w._alguien_habla() and w.cola.empty() and not w.actual
                    and not w.conv.get("activa") and not w.canal_pend):
                return True
            await asyncio.sleep(2)

    async def _charla(self, b: dict, nota: dict | None, pasos: list[dict], extra_abrir: str = "") -> None:
        """Una noticia = una conversación (conv activa: la sala y las réplicas solas se callan)."""
        w = self.w
        solo = self._solo()
        roles = {"presenta": b.get("presenta", "joy"), "comenta": b.get("comenta", "kuroki")}
        if solo:
            roles = {"presenta": solo, "comenta": solo}
            pasos = self.g.get("pasos_noticia_solo") or pasos
        elif not all(d in w.dolls for d in roles.values()):
            roles = dict(zip(("presenta", "comenta"), w.libres()[:2]))
        nombre = {k: w.dolls[d].estado.nombre for k, d in roles.items()}
        conv = w.conv = {"activa": True, "tema": f"BlackRose TV · {b['nombre']}" + (f": {nota['titulo']}" if nota else ""),
                         "turnos": len(pasos), "hechos": 0, "investigar": False, "reflexionar": False}
        vigente = lambda: w.conv is conv and conv["activa"] and self.activo and not self._saltar  # noqa: E731
        w.emitir({"type": "conv", "conv": conv})
        for r in w.dolls.values():
            r._idioma_usuario = self.lang
        try:
            for i, p in enumerate(pasos):
                if not vigente():
                    break
                quien = roles[p["quien"]]
                otra = nombre["comenta" if p["quien"] == "presenta" else "presenta"]
                instr = (extra_abrir + " " + p["instr"]).strip() if i == 0 else p["instr"]
                if solo:
                    otra = "el chat"
                    instr = ("Conduces SOLA y le hablas al público del stream: NO te dirijas a Blackrose ni a otra "
                             "doll y no empieces la frase con un nombre. " + instr)
                if i > 0:
                    instr = ("Ya contaste esta noticia hace un momento: NO repitas el titular, ni el medio, ni lo que "
                             "ya dijiste; sigue desde ahí con algo nuevo. " + instr)
                tema = self._tema(b, nota, instr, otra)
                self._emitir(paso=f"{w.dolls[quien].estado.nombre}: {p.get('tipo') or p.get('postura') or 'habla'}")
                if p.get("tipo") == "abrir" or solo or self.lang != "es":  # en otro idioma todo va por el turno con idioma fijo
                    fn = lambda q=quien, t=tema: w.dolls[q].espontaneo("tema", w.usuario, tema=t, idioma_turno=self.lang)
                else:
                    fn = lambda q=quien, t=tema, po=p.get("postura", ""): w.dolls[q].turno(
                        "", w.usuario, chime_in=True, tema=t, postura=po)
                await w._paso(fn, f"BlackRose TV: {w.dolls[quien].estado.nombre} ({b['id']} {i + 1}/{len(pasos)})")
                conv["hechos"] = i + 1
                w.emitir({"type": "conv", "conv": conv})
        finally:
            conv["activa"] = False
            if w.conv is conv:
                w.emitir({"type": "conv", "conv": conv})

    async def _aviso(self) -> dict | None:
        """El «Vuelvo en X min con …» que pone ella en el overlay (:8822/api/aviso); None si no hay o no responde."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1.5)) as s:
                async with s.get(self.g.get("aviso_url", "http://127.0.0.1:8822/api/aviso")) as r:
                    d = await r.json(content_type=None)
        except Exception:  # noqa: BLE001  (overlay caído: sin aviso)
            return None
        if not d.get("activo"):
            return None
        d["min"] = max(1, round((float(d.get("hasta", 0)) - time.time()) / 60))
        return d

    async def _cuna(self, tipo: str, b: dict | None = None, texto: str = "") -> None:
        """Cuña de la emisora: mensaje fijo (voz de la conductora, con lipsync) + transición del overlay (estado.cuna)."""
        w = self.w
        cn = self.g.get("cunas_" + self.lang) if self.lang != "es" else None
        opciones = ((cn if cn is not None else self.g.get("cunas")) or {}).get(tipo) or []
        d = self._solo() or (self.g.get("cunas_doll") or "kuroki")
        if d not in w.dolls or not self.activo:
            return
        if tipo == "aviso":
            av = await self._aviso()
            if not av:
                return
            texto = random.choice(opciones).format(min=av["min"], con=av.get("con", "Fast Penguin"),
                                                   minutos=f"{av['min']} minuto" + ("s" if av["min"] != 1 else "")) if opciones else ""
        elif not texto and opciones:
            texto = random.choice(opciones)
        if tipo == "ident" and b:  # a veces el identificador pasa directo a anunciar el bloque
            extra = (b.get("cuna_entrada" if self.lang == "es" else "cuna_entrada_" + self.lang) or "").strip()
            if extra and random.random() < 0.6:
                texto = f"{texto} {extra}"
        if not texto and not self.g.get("cunas_mudas", True):
            return
        self._cuna_n += 1
        self._emitir(cuna={"id": self._cuna_n, "tipo": tipo, "t": time.time()}, paso=f"cuña: {tipo}")
        if texto:
            await w._paso(lambda: w.dolls[d].decir(texto, f"cuña:{tipo}"), f"BlackRose TV: cuña {tipo}")
        else:
            await asyncio.sleep(float(self.g.get("cuna_segs", {}).get(tipo, 4)))
        await asyncio.sleep(0.4)

    async def _redaccion(self, b: dict, pasos: list[dict]) -> bool:
        """Emite la próxima noticia de la redacción (/redaccion en el overlay :8822) para este bloque, si hay."""
        from . import redaccion as R
        n = R.siguiente(b["id"])
        if not n or not await self._esperar_turno():
            return False
        R.marcar(n["id"], "al_aire", emitida_t=time.time())
        nota = R.a_nota(n)
        try:
            await self._cuna("ultima_hora", b=b)
            self._emitir(noticia={"titulo": nota["titulo"], "fuente": nota["fuente"], "imagenes": nota["imagenes"],
                                  "propia": True})
            abrir = "Presenta esta noticia como EXCLUSIVA de la redacción de BlackRose TV, que trajo Blackrose."
            await self._charla(b, nota, self.g.get("pasos_noticia_redaccion") or pasos, abrir)
        finally:
            R.marcar(n["id"], "emitida")
            self._emitir(noticia=None)
        await asyncio.sleep(random.uniform(*self.g.get("pausa_entre_noticias", [18, 35])))
        return True

    # --- segmento periodístico (INFORME ESPECIAL con infografía): lámina por lámina, narrado con texto fijo (sin LLM: cero tokens) ---
    async def _seg_post(self, d: dict) -> None:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as s:
                await s.post(self.g.get("segmento_url", "http://127.0.0.1:8822/api/segmento"), json=d)
        except Exception as e:  # noqa: BLE001  (overlay caído: se narra igual)
            log.warning("segmento overlay: %s", e)

    async def _libre(self) -> bool:
        w = self.w
        while not self._seg_stop:
            if not w._alguien_habla() and w.cola.empty() and not w.actual:
                return True
            await asyncio.sleep(1)
        return False

    async def _segmento(self, sid: str) -> None:
        w = self.w
        try:
            data = json.loads((Path(__file__).resolve().parent / "segmentos" / f"{sid}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("segmento %s: %s", sid, e)
            return
        self._seg_stop, self.segmento = False, sid
        slides = data["slides"]
        conv = w.conv = {"activa": True, "tema": f"INFORME ESPECIAL · {data.get('titulo', sid)}", "turnos": len(slides), "hechos": 0,
                         "investigar": False, "reflexionar": False}   # la sala y las réplicas solas se callan
        w.emitir({"type": "conv", "conv": conv})
        try:
            await self._libre()
            for i, sl in enumerate(slides):
                if self._seg_stop:
                    break
                partes = sl.get("habla") or []
                await self._seg_post({"activo": True, "i": i, "n": len(slides), "slide": {k: v for k, v in sl.items() if k != "habla"},
                                      "quien": partes[0]["quien"] if partes else "", "t": time.time()})
                await asyncio.sleep(1.6)   # que entre la lámina antes de hablar
                for p in partes:
                    if self._seg_stop or p["quien"] not in w.dolls:
                        continue
                    await self._libre()
                    await self._seg_post({"activo": True, "i": i, "n": len(slides), "slide": {k: v for k, v in sl.items() if k != "habla"}, "quien": p["quien"], "t": time.time()})
                    await w._paso(lambda q=p["quien"], t=p["texto"]: w.dolls[q].decir(t, "segmento"), f"Informe especial: {w.dolls[p['quien']].estado.nombre} ({i + 1}/{len(slides)})")
                    await asyncio.sleep(0.6)
                conv["hechos"] = i + 1
                await asyncio.sleep(1.0)
        finally:
            conv["activa"] = False
            w.emitir({"type": "conv", "conv": conv})
            await asyncio.sleep(6)   # la última lámina se queda un rato
            await self._seg_post({"activo": False})
            self.segmento = None

    async def _bloque(self, b: dict, sig: dict) -> None:
        w = self.w
        self._act = b
        fijo = self._fijo == b["id"]
        self._emitir(bloque=self._publico(b), siguiente=self._publico(sig), noticia=None, paso="cortina")
        notas = await self.noticias(b) if int(b.get("noticias", 3)) > 0 else []
        temas = random.sample(b.get("respaldo") or [], len(b.get("respaldo") or []))  # otro orden cada vuelta
        if not notas:
            notas = [None] * min(int(b.get("respaldo_n", 2)), len(temas))
        pasos = b.get("pasos") or self.g["pasos_noticia"]
        if not fijo and await self._esperar_turno() and not self._ir_a:  # identificador de la emisora antes de cada bloque
            await self._cuna("ident", b=b)
            if self._bloques_hechos % 2 == 1:
                await self._cuna("aviso", b=b)  # solo habla si hay aviso activo (Vuelvo en X min…)
        for k, nota in enumerate(notas + [None]):  # el [None] final = hueco para la redacción al cerrar el bloque
            if not await self._esperar_turno() or self._ir_a:
                return
            self._saltar = False
            await self._redaccion(b, pasos)  # si Blackrose dejó una noticia en la redacción, va primero
            if k == len(notas):
                break
            if k > 0:  # entre noticias: un spot cada tantas noticias; si no, corte rápido o recordatorio de los mercados
                self._spot_cuenta = getattr(self, "_spot_cuenta", 0) + 1
                spots, cada = self.g.get("spots") or [], int(self.g.get("spot_cada_noticias", 0) or 0)
                if spots and cada and self._spot_cuenta % cada == 0:
                    self._spot_i = getattr(self, "_spot_i", -1) + 1
                    await self._cuna(spots[self._spot_i % len(spots)], b=b)
                else:
                    await self._cuna("corte" if fijo or random.random() < 0.7 else "mercados", b=b)
            if nota and time.time() - nota["t"] < 2.5 * 3600 and random.random() < 0.6:
                await self._cuna("ultima_hora", b=b)
            if nota:
                self._marcar_vista(nota["titulo"])
                self._emitir(noticia={"titulo": nota["titulo"], "fuente": nota["fuente"]})
            else:
                tema = temas[k % len(temas)]
                self._emitir(noticia={"titulo": tema, "fuente": "BlackRose TV"})
            abrir = b.get("abrir", "") if k == 0 else "Pasa a la siguiente noticia del bloque con una transición corta."
            bb = b if nota else {**b, "tono": b.get("tono", "") + f" TEMA DE FONDO: {tema}."}
            await self._charla(bb, nota, pasos, abrir)
            await asyncio.sleep(random.uniform(*self.g.get("pausa_entre_noticias", [18, 35])))
        # cierre del bloque + promo cada tantos bloques
        if not fijo and await self._esperar_turno() and not self._ir_a:
            self._saltar = False
            self._emitir(noticia=None, paso="cierre")
            instr = self.g.get("cierre_bloque", "").format(bloque=b["nombre"], siguiente=sig["nombre"])
            await self._charla(b, None, [{"quien": "presenta", "tipo": "abrir", "instr": instr}])
        self._bloques_hechos += 1
        cada = int(self.g.get("promo_cada_bloques", 2) or 0)
        if cada and not fijo and self._bloques_hechos % cada == 0 and await self._esperar_turno():
            d = self._solo() or (w.cfg.get("promo") or {}).get("doll", "joy")
            await self._cuna("volvemos", b=b)
            if d in w.dolls:
                await w._paso(lambda: w.dolls[d].espontaneo("promo", w.usuario, idioma_turno=self.lang),
                              "BlackRose TV: promo del canal")

    async def loop(self) -> None:
        await asyncio.sleep(20)  # que arranquen las dolls y el agente
        while True:
            if not self.activo:
                self._emitir(paso="apagado")
                while not self.activo:
                    await asyncio.sleep(3)
            try:  # el guion se relee en cada bloque: se puede editar el yaml en vivo
                g = yaml.safe_load(open(self.archivo, encoding="utf-8"))
                self.g, self.bloques = g, g["bloques"]
                self.i %= len(self.bloques)
            except Exception as e:  # noqa: BLE001  (yaml roto: sigue con el anterior)
                log.warning("programacion.yaml: %s (sigo con el guion anterior)", e)
            if self._ir_a:
                self.i = next((j for j, b in enumerate(self.bloques) if b["id"] == self._ir_a), self.i)
                self._ir_a = None
            b, sig = self.bloques[self.i], self.bloques[self._sig(self.i)]
            try:
                await self._bloque(b, sig)
            except Exception as e:  # noqa: BLE001  (un bloque roto no apaga el canal)
                log.warning("bloque %s falló: %s", b["id"], e)
                await asyncio.sleep(30)
            if self._ir_a is None:
                self.i = self._indice(self._fijo) if self._fijo else self._sig(self.i)

    def _indice(self, bid: str | None) -> int:
        return next((j for j, b in enumerate(self.bloques) if b["id"] == bid), 0)

    def _sig(self, i: int) -> int:
        """Siguiente bloque de la rueda (los de `rotar: false` solo salen si se piden con «bloque» o «fijar»)."""
        if self._fijo:
            return self._indice(self._fijo)
        for k in range(1, len(self.bloques) + 1):
            j = (i + k) % len(self.bloques)
            if self.bloques[j].get("rotar", True):
                return j
        return i

    # --- control -------------------------------------------------------------------------
    def accion(self, d: dict) -> dict:
        a = str(d.get("accion") or "")
        if a in ("on", "off"):
            self.activo = a == "on"
            if not self.activo:
                self._saltar = True
        elif a == "siguiente":
            self._saltar = True
        elif a == "solo":  # {"accion":"solo","doll":"kuroki"}  ·  doll vacío/"off" = vuelven a conducir las dos
            dd = str(d.get("doll") or "")
            self.solo = dd if dd in self.w.dolls else None
        elif a == "idioma":  # {"accion":"idioma","lang":"ja"} · es | en | ja
            lg = str(d.get("lang") or "es")
            if lg not in ("es", "en", "ja"):
                return {"ok": False, "error": "lang: es | en | ja"}
            self.lang = lg
            self._emitir(idioma=lg)
        elif a == "fijar":  # {"accion":"fijar","id":"fastpenguin"}: repite ese bloque sin avanzar · sin id = vuelve la rueda
            bid = str(d.get("id") or "")
            if bid and not any(b["id"] == bid for b in self.bloques):
                return {"ok": False, "error": "bloque desconocido"}
            self._fijo = bid or None
            if bid:
                self._ir_a, self._saltar = bid, True
        elif a == "segmento":  # {"accion":"segmento","id":"apagon"} lo emite · {"accion":"segmento","id":"off"} lo corta
            sid = str(d.get("id") or "")
            if sid == "off":
                self._seg_stop = True
                self.w.dolls and [r.cancelar_lectura() for r in self.w.dolls.values()]
            elif self.segmento:
                return {"ok": False, "error": f"ya hay un segmento en curso: {self.segmento}"}
            elif (Path(__file__).resolve().parent / "segmentos" / f"{sid}.json").exists():
                asyncio.get_running_loop().create_task(self._segmento(sid))
            else:
                return {"ok": False, "error": "segmento desconocido"}
        elif a == "cuna":  # {"accion":"cuna","tipo":"ident","texto"?}: la dice ahora (cuando le toque el turno)
            asyncio.get_running_loop().create_task(self._cuna(str(d.get("tipo") or "ident"), texto=str(d.get("texto") or "")))
        elif a == "bloque" and any(b["id"] == d.get("id") for b in self.bloques):
            self._ir_a, self._saltar = d["id"], True
        else:
            return {"ok": False, "error": "acción: on | off | siguiente | bloque (+id) | fijar (+id) | idioma (+lang) | solo (+doll) | cuna (+tipo) | segmento (+id|off)"}
        self._emitir(solo=self.solo)
        return {"ok": True, **self.estado}

    def info(self) -> dict:
        return {**self.estado, "activo": self.activo, "canal": self.g.get("canal", "BlackRose TV"),
                "lema": self.g.get("lema", ""), "bloques": [self._publico(b) for b in self.bloques]}


class Mercados:
    """Marquesina de BlackRose TV: acciones tech (Yahoo, sin clave) y criptos (CoinGecko), cada 5 min, en memoria."""
    TICK = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "TSM", "NFLX", "SONY", "NTDOY", "ORCL"]
    CRIPTO = [("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL"), ("ripple", "XRP"), ("binancecoin", "BNB"),
              ("dogecoin", "DOGE"), ("cardano", "ADA"), ("monero", "XMR"), ("the-open-network", "TON")]
    NOMBRES = {"NTDOY": "NINTENDO", "GOOGL": "GOOGLE", "TSM": "TSMC"}

    def __init__(self):
        self.datos: dict = {"acciones": [], "cripto": [], "t": 0}

    async def _json(self, s: aiohttp.ClientSession, url: str):
        async with s.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def _accion(self, s, t: str) -> dict | None:
        try:
            m = (await self._json(s, f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=1d&interval=1d"))[
                "chart"]["result"][0]["meta"]
            p, prev = m["regularMarketPrice"], m.get("chartPreviousClose") or m.get("previousClose")
            return {"s": self.NOMBRES.get(t, t), "p": p, "c": (p / prev - 1) * 100 if prev else 0}
        except Exception as e:  # noqa: BLE001
            log.info("acción %s: %s", t, e)
            return None

    async def loop(self) -> None:
        while True:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
                    acc = [a for a in await asyncio.gather(*(self._accion(s, t) for t in self.TICK)) if a]
                    if acc:
                        self.datos["acciones"] = acc
                    try:
                        ids = ",".join(i for i, _ in self.CRIPTO)
                        c = await self._json(s, f"https://api.coingecko.com/api/v3/simple/price?ids={ids}"
                                                "&vs_currencies=usd&include_24hr_change=true")
                        self.datos["cripto"] = [{"s": sim, "p": c[i]["usd"], "c": c[i].get("usd_24h_change") or 0}
                                                for i, sim in self.CRIPTO if i in c]
                    except Exception as e:  # noqa: BLE001  (CoinGecko limita: queda lo anterior)
                        log.info("cripto: %s", e)
                self.datos["t"] = time.time()
            except Exception as e:  # noqa: BLE001
                log.warning("mercados: %s", e)
            await asyncio.sleep(300)
