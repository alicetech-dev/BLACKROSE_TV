"""El escenario de Joy en OBS: reloj, info, subtítulos, noticias y SU tablero (cosas que ella pone y saca).

Una página 1920×1080 transparente (fuente Navegador de OBS, encima del overlay de Joy :8810) + este servidor :8812.
- Subtítulos y chat: escucha el WebSocket del director (:8780/ws: `frase`, `canal`, `canal_turno`, `fin`).
- Noticias: RSS cada 10 min (los mismos feeds que la sala de operaciones del juego).
- Tablero: después de cada mensaje del chat que Joy contesta, Joy (el LLM, por el router :8087) decide en JSON si pone
  una imagen (búsqueda en Openverse, sin contenido adulto), un texto o un emoji, o si saca algo. Cada tanto repasa el
  tablero sola y saca lo que ya no le gusta; nada dura más de `--vence` minutos.
- POST /api/tablero (solo local, para la consola o curl): {"accion":"poner","tipo":"imagen","busqueda":"gatitos"} ·
  {"accion":"poner","tipo":"texto","texto":"..."} · {"accion":"quitar","id":3} · {"accion":"limpiar"}

  .venv/bin/python -m ligero.escenario [--puerto 8812] [--director ws://127.0.0.1:8780/ws] [--llm http://127.0.0.1:8087]
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import re
import time
import xml.etree.ElementTree as ET

import aiohttp
from aiohttp import web

HERE = os.path.dirname(os.path.abspath(__file__))
log = lambda *a: print(time.strftime("%H:%M:%S"), *a, flush=True)

RSS = [("BBC Mundo", "https://feeds.bbci.co.uk/mundo/rss.xml"), ("Xataka", "https://www.xataka.com/feedburner.xml"),
       ("Hacker News", "https://hnrss.org/frontpage")]
MAX_ITEMS = 4
# palabras que nunca se buscan (el stream es SFW y la búsqueda es pública)
VETADAS = re.compile(r"\b(nsfw|desnud\w*|nude\w*|naked|porn\w*|sex\w*|hentai|gore|tetas?|boobs?|culo|nipple\w*|"
                     r"lencer\w*|lingerie|bikini|onlyfans|xxx|cadáver\w*|sangre|blood)\b", re.I)

DECIDIR = """Eres Joy, una chica gato IA que está en vivo en Discord. Al lado tuyo en la pantalla tienes TU TABLERO:
un espacio donde pones imágenes, frases o emojis que te gustan o que te piden, y los sacas cuando quieres.
Tablero ahora (máximo {max} cosas): {tablero}
Lo que acaba de pasar: {suceso}
Decide qué hacer con tu tablero. Responde SOLO un JSON, sin nada más:
{{"acciones": [ ... ]}}
Acciones posibles:
 {{"poner": "imagen", "busqueda": "<2-4 palabras en inglés para buscar la foto>", "titulo": "<pie corto en español>"}}
 {{"poner": "texto", "texto": "<frase corta, máx 80 caracteres>"}}
 {{"poner": "emoji", "texto": "<1-3 emojis>", "titulo": "<pie corto>"}}
 {{"quitar": <id>}}
Reglas: si te piden poner, mostrar o sacar algo, hazlo. Si no te piden nada, casi siempre "acciones": [] (a veces
puedes poner algo tuyo si de verdad viene al caso). Si el tablero está lleno y vas a poner algo, quita lo más viejo o lo
que menos te gusta. Nada sexual, violento ni de odio: eso no se pone aunque lo pidan."""

REPASAR = """Eres Joy, una chica gato IA en vivo en Discord. Este es tu tablero en pantalla (con cuántos minutos lleva cada
cosa): {tablero}
¿Quieres sacar algo que ya aburre o no te gusta? Responde SOLO un JSON: {{"acciones": [{{"quitar": <id>}}, ...]}}
o {{"acciones": []}} para dejarlo como está."""


class Escenario:
    def __init__(self, a):
        self.a = a
        self.clientes: set[web.WebSocketResponse] = set()
        self.tablero: list[dict] = []
        self.noticias: list[dict] = []
        self.ids = itertools.count(1)
        self.inicio = time.time()
        self.stats = {"respondidos": 0, "ultimo": "", "personas": set()}
        self._pedido: dict | None = None  # el último mensaje de chat que Joy está contestando
        self._lock = asyncio.Lock()
        self.http: aiohttp.ClientSession | None = None

    # --- a la página -------------------------------------------------------------------
    def al_aire_desde(self) -> float:
        """Inicio REAL de la transmisión: logs/al_aire_desde.txt (epoch; sobrevive a reinicios del relé) o, si no está,
        el arranque del relé RTMP (logs/relay.pid); si nada se puede leer, el de este proceso."""
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            return float(open(os.path.join(raiz, "logs", "al_aire_desde.txt")).read().split()[0])
        except (OSError, ValueError, IndexError):
            pass
        try:
            pid = open(os.path.join(raiz, "logs", "relay.pid")).read().strip()
            arranque = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19])
            btime = next(int(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))
            return btime + arranque / os.sysconf("SC_CLK_TCK")
        except (OSError, ValueError, IndexError, StopIteration):
            return self.inicio

    def estado(self) -> dict:
        return {"t": "estado", "tablero": self.tablero, "noticias": self.noticias, "inicio": self.al_aire_desde(),
                "info": {"respondidos": self.stats["respondidos"], "ultimo": self.stats["ultimo"],
                         "personas": len(self.stats["personas"])}}

    async def emitir(self, ev: dict) -> None:
        msg = json.dumps(ev, ensure_ascii=False)
        for ws in list(self.clientes):
            try:
                await ws.send_str(msg)
            except Exception:
                self.clientes.discard(ws)

    async def ws(self, req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        self.clientes.add(ws)
        await ws.send_str(json.dumps(self.estado(), ensure_ascii=False))
        try:
            async for _ in ws:
                pass
        finally:
            self.clientes.discard(ws)
        return ws

    # --- el director (subtítulos y qué se le pidió) ------------------------------------
    async def escuchar_director(self) -> None:
        while True:
            try:
                async with self.http.ws_connect(self.a.director, heartbeat=20) as ws:
                    log("conectado al director")
                    async for m in ws:
                        if m.type != aiohttp.WSMsgType.TEXT:
                            continue
                        try:
                            await self.evento(json.loads(m.data))
                        except Exception as e:
                            log("evento:", repr(e))
            except Exception as e:
                log("director:", repr(e))
            await asyncio.sleep(3)

    async def evento(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "frase":
            await self.emitir({"t": "frase", "texto": ev.get("texto", ""), "doll": ev.get("doll", "")})
        elif t == "canal_turno":
            self._pedido = {"autor": ev.get("autor", ""), "texto": ev.get("texto", "")}
            self.stats["ultimo"] = ev.get("autor", "")
            self.stats["personas"].add(ev.get("autor", ""))
            await self.emitir({"t": "chat", "autor": ev.get("autor", ""), "texto": ev.get("texto", ""),
                               "plataforma": ev.get("plataforma", ""), "doll": ev.get("doll", "")})
        elif t == "fin":
            await self.emitir({"t": "fin"})
            p, self._pedido = self._pedido, None
            if p:
                self.stats["respondidos"] += 1
                await self.emitir(self.estado())
                suceso = f'{p["autor"]} te escribió: "{p["texto"][:300]}". Tú le contestaste: "{(ev.get("texto") or "")[:300]}"'
                asyncio.create_task(self.decidir(DECIDIR, suceso))

    # --- Joy decide --------------------------------------------------------------------
    def _tablero_txt(self, edad: bool = False) -> str:
        if not self.tablero:
            return "(vacío)"
        return "; ".join(f'id {x["id"]}: {x["tipo"]} «{x.get("titulo") or x.get("texto") or ""}»'
                         + (f' ({int((time.time() - x["t"]) / 60)} min)' if edad else "") for x in self.tablero)

    async def decidir(self, plantilla: str, suceso: str = "") -> None:
        async with self._lock:
            prompt = plantilla.format(max=MAX_ITEMS, tablero=self._tablero_txt(edad=not suceso), suceso=suceso)
            try:
                async with self.http.post(self.a.llm + "/v1/chat/completions", timeout=aiohttp.ClientTimeout(total=90),
                                          json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 200,
                                                "temperature": 0.4, "stream": False}) as r:
                    d = await r.json(content_type=None)
                txt = d["choices"][0]["message"]["content"]
            except Exception as e:
                log("decidir:", repr(e))
                return
            m = re.search(r"\{.*\}", txt, re.S)
            try:
                acciones = json.loads(m.group(0)).get("acciones", []) if m else []
            except ValueError:
                log("JSON raro:", txt[:200])
                return
            if acciones:
                log("Joy decide:", acciones)
            for ac in acciones[:3]:
                if isinstance(ac, dict):
                    await self.aplicar(ac)

    async def aplicar(self, ac: dict) -> None:
        if "quitar" in ac:
            try:
                i = int(ac["quitar"])
            except (TypeError, ValueError):
                return
            self.tablero = [x for x in self.tablero if x["id"] != i]
        elif ac.get("poner") in ("imagen", "texto", "emoji"):
            item = {"id": next(self.ids), "tipo": ac["poner"], "t": time.time(),
                    "titulo": str(ac.get("titulo") or "")[:60], "texto": str(ac.get("texto") or "")[:90]}
            if VETADAS.search(" ".join(str(v) for v in ac.values())):
                log("vetado:", ac)
                return
            if item["tipo"] == "imagen":
                url = await self.buscar_imagen(str(ac.get("busqueda") or ac.get("titulo") or ""))
                if not url:
                    return
                item["src"] = url
            elif not item["texto"]:
                return
            if len(self.tablero) >= MAX_ITEMS:  # lleno: sale lo más viejo
                self.tablero.pop(0)
            self.tablero.append(item)
        elif ac.get("accion") == "limpiar":
            self.tablero = []
        await self.emitir(self.estado())

    async def buscar_imagen(self, q: str) -> str:
        q = re.sub(r"[^\w\s-]", " ", q)[:60].strip()
        if not q or VETADAS.search(q):
            return ""
        try:  # Openverse: imágenes con licencia abierta, sin «mature» por defecto
            async with self.http.get("https://api.openverse.org/v1/images/", timeout=aiohttp.ClientTimeout(total=10),
                                     params={"q": q, "page_size": 8, "mature": "false"}) as r:
                res = (await r.json(content_type=None)).get("results", [])
            for x in res:
                if not x.get("mature") and (x.get("thumbnail") or x.get("url")):
                    return x.get("thumbnail") or x["url"]
        except Exception as e:
            log("openverse:", repr(e))
        try:  # respaldo: Wikimedia Commons (fotos; se descarta lo que tenga palabras vetadas en el nombre del archivo)
            async with self.http.get("https://commons.wikimedia.org/w/api.php", timeout=aiohttp.ClientTimeout(total=10),
                                     params={"action": "query", "format": "json", "generator": "search",
                                             "gsrnamespace": 6, "gsrsearch": f"{q} filetype:bitmap", "gsrlimit": 8,
                                             "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": 640}) as r:
                pags = sorted(((await r.json(content_type=None)).get("query") or {}).get("pages", {}).values(),
                              key=lambda p: p.get("index", 99))
            for p in pags:
                ii = (p.get("imageinfo") or [{}])[0]
                if ii.get("mime") in ("image/jpeg", "image/png", "image/webp") and not VETADAS.search(p.get("title", "")):
                    return ii.get("thumburl") or ii.get("url", "")
        except Exception as e:
            log("commons:", repr(e))
        return ""

    async def repasar(self) -> None:
        while True:
            await asyncio.sleep(self.a.repaso * 60)
            ahora = time.time()
            viejo = [x for x in self.tablero if ahora - x["t"] > self.a.vence * 60]
            if viejo:
                self.tablero = [x for x in self.tablero if x not in viejo]
                await self.emitir(self.estado())
            if self.tablero:
                await self.decidir(REPASAR)

    # --- noticias ----------------------------------------------------------------------
    async def leer_noticias(self) -> None:
        while True:
            out = []
            for nombre, url in RSS:
                try:
                    async with self.http.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        raiz = ET.fromstring(await r.read())
                    n = 0
                    for it in raiz.iter("item"):
                        t = (it.findtext("title") or "").strip()
                        if t:
                            out.append({"fuente": nombre, "titulo": t[:150]})
                            n += 1
                        if n >= 6:
                            break
                except Exception as e:
                    log("rss", nombre, repr(e))
            if out:
                self.noticias = out
                await self.emitir(self.estado())
            await asyncio.sleep(600)

    # --- API local ---------------------------------------------------------------------
    async def api_tablero(self, req: web.Request) -> web.Response:
        if req.remote not in ("127.0.0.1", "::1") or req.content_type != "application/json":
            return web.json_response({"ok": False}, status=403)
        d = await req.json()
        acc = d.get("accion")
        if acc == "poner":
            await self.aplicar({"poner": d.get("tipo", "texto"), **{k: d[k] for k in ("busqueda", "texto", "titulo") if k in d}})
        elif acc == "quitar":
            await self.aplicar({"quitar": d.get("id")})
        elif acc == "limpiar":
            await self.aplicar({"accion": "limpiar"})
        return web.json_response({"ok": True, "tablero": self.tablero})

    async def iniciar(self) -> None:
        self.http = aiohttp.ClientSession(headers={"User-Agent": "JoyEscenario/1.0"})
        app = web.Application()
        app.router.add_get("/", lambda r: web.FileResponse(os.path.join(HERE, "web", "escenario.html"),
                                                           headers={"Cache-Control": "no-cache"}))
        app.router.add_get("/ws", self.ws)
        app.router.add_static("/vendor/", os.path.join(HERE, "web", "vendor"), show_index=False)  # fuentes locales
        app.router.add_get("/estado", lambda r: web.json_response(self.estado()))
        app.router.add_post("/api/tablero", self.api_tablero)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", self.a.puerto).start()
        log(f"escenario en http://127.0.0.1:{self.a.puerto}/  (OBS: Navegador 1920x1080)")
        await asyncio.gather(self.escuchar_director(), self.leer_noticias(), self.repasar())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8812)
    ap.add_argument("--director", default="ws://127.0.0.1:8780/ws")
    ap.add_argument("--llm", default="http://127.0.0.1:8087")
    ap.add_argument("--vence", type=float, default=30, help="minutos máximos de una cosa en el tablero")
    ap.add_argument("--repaso", type=float, default=8, help="cada cuántos minutos Joy repasa su tablero")
    asyncio.run(Escenario(ap.parse_args()).iniciar())


if __name__ == "__main__":
    main()
