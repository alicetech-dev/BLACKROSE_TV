"""Consola de las dolls: botonera tipo Stream Deck (gestos, caras, modos, autonomía, acciones), chat, estado, y
subtítulos para OBS.

  .venv/bin/python -m director.web            # http://127.0.0.1:8780  (subtítulos: /subtitulos)
                                              # overlay del stream: /charlita (en vivo) y /empezamos
  .venv/bin/python -m director.web --lan      # también desde el celular en la red local

WebSocket /ws. Del navegador llega:
  {"type": "msg", "doll": id|null, "text"}           mensaje (sin doll: la nombrada en el texto o la última)
  {"type": "escribiendo", "doll": id|null}           estás escribiendo: te miran y escuchan
  {"type": "cuerpo", "doll", "intent": {...}}        gesto/emoción/mirada/pose/baile manual a su joy_vmc
  {"type": "modo", "doll", "modo"}                   modo de charla del agente (chat, trance, spa, lecture...)
  {"type": "autonomia", "doll", "modo"}              vida | sleep | off (loops del agente, hablan solas)
  {"type": "sala", "activo": bool}                   autonomía de la sala: en los silencios hablan solas/entre ellas
  {"type": "espontaneo", "doll", "tipo"}             pensamiento | pregunta | a_la_otra | silencio
  {"type": "dialogo", "turnos": n}                   que charlen entre ellas n turnos
  {"type": "impulso", "doll", "impulso"}             reflect | research | monologue | lore (latido a mano; lo dice)
  {"type": "guion", "doll", "texto", "escena", "tempo"?}   texto directo a la voz con la animación de una escena (sin IA;
                                                     "Joy: ..." / "Bambi: ..." al inicio de línea cambia quien habla)
  {"type": "bailar", "baile", "quienes": [ids]|"ambas", "con": {"baile","camara","musica"}}   baile MMD de Warudo
  {"type": "bailar_parar"} · {"type": "musica_sola", "baile"}                                 (cámara y canción aparte)
  {"type": "titere", "doll", "activo": bool}         modo marioneta: la manejás vos, la IA no genera nada (idle sigue)
  {"type": "callar"} · {"type": "reset", "doll"}
  {"type": "silencio", "activo": bool, "motivo"}   pausa el habla automática (sala, réplicas, autonomía) mientras haya
                                                   algún motivo (usuaria = 🔇 del visor, modo = modo de voz sin LLM)
  {"type": "canal", "activo": bool}                  chat del canal: que lo contesten solas o no
  {"type": "perfil", "perfil": "habitual"|"ligero"}  (solo --sfw) cambia de perfil: reinicia todo con dolls.sh restart
  {"type": "canal_responder", "id", "doll"?}         contestar YA ese mensaje del chat (clic en la consola)

Chat del canal (modo stream, ver canal.py): cada mensaje llega a chat_canal() — desde los lectores de YouTube/Twitch
o por POST /api/canal {"autor", "texto", "plataforma"?} — y se contesta de a uno, con pausa, como espectador.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
import os
import random
import re
import subprocess
import time

from aiohttp import WSMsgType, web

from . import __main__ as D
from . import canal as C
PLATAFORMAS = {"twitch": "Twitch", "youtube": "YouTube", "kick": "Kick", "discord": "Discord"}
from . import escenas as E
from . import bailes as B
from . import legajo as L
from . import voz_web as VW
from .voz import PRESETS, crear, idioma, mantener_xtts, principal_xtts

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("director.web")
IMPULSO_AVISO = {"reflect": "está reflexionando", "research": "está investigando en la web (puede tardar)",
                 "monologue": "está armando un monólogo", "lore": "está recordando algo del Instituto"}



def titulo_legible(t: str) -> bool:
    """Un título que dice algo (al menos dos palabras de verdad), no un nombre random tipo "a8f3c91e" o "VID_20240101"."""
    palabras = [p for p in re.findall(r"[^\W\d_]{3,}", t or "") if re.search(r"[aeiouyAEIOUY]", p)]
    return len(palabras) >= 2

# --- bailes en el overlay ligero (ligero/web/bailes/*.json, tools/vmd_a_vrm.py) ---------------------------------
_RE_BAILE = re.compile(r"\b(bail\w*|danz\w*|dance\w*|baile\w*|muev\w* el cuerpo|twerk)\b", re.I)
_RE_NO_BAILE = re.compile(r"\b(para|pará|deja|detente|basta|stop|no bail\w*|ya no)\b.{0,20}\b(bail\w*|danz\w*|dance\w*)|\b(bail\w*|danz\w*)\b.{0,12}\b(stop|basta|para)\b", re.I)
_BAILES_OVERLAY = {"saso": r"say ?so|saso|doja", "side": r"side ?to ?side|ariana|nicki"}


async def baile_overlay(texto: str, puerto: int = 8810) -> str | None:
    """Si el mensaje pide bailar (o parar), se lo avisa al overlay de Joy. Devuelve el id, "" si lo corta, None si no era."""
    import urllib.request
    if _RE_NO_BAILE.search(texto):
        id_ = ""
    elif _RE_BAILE.search(texto):
        id_ = next((k for k, rx in _BAILES_OVERLAY.items() if re.search(rx, texto, re.I)), random.choice(list(_BAILES_OVERLAY)))
    else:
        return None

    def _post():
        req = urllib.request.Request(f"http://127.0.0.1:{puerto}/api/baile", json.dumps({"id": id_}).encode(),
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    try:
        await asyncio.get_running_loop().run_in_executor(None, _post)
    except Exception as e:  # noqa: BLE001  (sin overlay ligero no pasa nada)
        log.warning("baile: no pude avisarle al overlay: %s", e)
        return None
    return id_



class Web:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.clientes: set[web.WebSocketResponse] = set()
        self.dolls: dict = {}
        self.historial: list[dict] = []  # últimos eventos de chat, para quien abre la página después
        self.ultima = None
        # acciones que hablan, de a una (un solo 4B, un micrófono), por prioridad: 0 tus mensajes · 1 botones ·
        # 2 conversación con tema · 3 sala autónoma. La consola ve qué se está haciendo y qué hay en la fila.
        self.cola: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self.actual = ""
        self.en_fila: dict[int, str] = {}
        self.conv: dict = {"activa": False}
        self._sala_id = 0
        self.cadena = 0  # réplicas encadenadas desde lo último que no era respuesta
        self._en_replica = False
        self.ultimo_habla: tuple = (None, 0.0)  # (doll, cuándo terminó de hablar)
        self._conv_task: asyncio.Task | None = None
        self.modos: dict[str, list[str]] = {}
        self.autonomia: dict[str, str] = {}
        sala = cfg.get("sala", {})
        self.sala = {"activo": bool(sala.get("activo", False)), "silencio": sala.get("silencio", [35, 90]),
                     "dialogo_max": int(sala.get("dialogo_max", 3)), "replicar": float(sala.get("replicar", 0.85)),
                     "posturas": sala.get("posturas") or {}}
        self.silencio: set[str] = set()  # motivos del silencio (vacío = hablan solas como siempre)
        self.ultima_actividad = time.monotonic()
        self.usuario = cfg["usuario"]
        self.vr = {"activo": False, "video": "", "pista": "", "playlist": "", "dormida": False, "zona": "", "evento": "", "visto": 0.0}
        # el legajo de la operadora en el Instituto (solo con `legajo: true`, el modo privado): progreso y trofeos
        self.legajo = L.Legajo(os.path.join(HERE, "legajo.json")) if cfg.get("legajo") else None
        self._trofeos: list[str] = []  # hitos por entregar (si estás dormida, esperan a que te despiertes)
        self.ocurrencias = bool(sala.get("ocurrencias", False))  # turno "ocurrencia" (solo el pack adulto lo entiende)  # el visor VR del celular (vr/servidor.py) y su tele
        self.escenas = E.escenas(cfg)
        self.bailes = B.Bailes(B.cargar(), emitir=lambda ev: self.emitir(ev),
                              path=os.path.join(B.HERE, "bailes.yaml"),
                              cuerpos=lambda: {d: r.cuerpo for d, r in self.dolls.items()})  # baile/cámara/música en Warudo
        self._guion_id = 0  # callar lo cambia: los tramos que faltan de un guion con varias voces se descartan
        self.impulsos: dict[str, list[str]] = {}
        self.autonomias: dict[str, list[str]] = {}
        # chat del canal: mensajes de espectadores sin contestar (se contestan de a uno, con pausa entre uno y otro)
        motor = next((d.get("voz", {}).get("motor") for d in cfg["dolls"].values()), "")
        self.voz_actual = next((k for k, p in PRESETS.items() if p["motor"] == motor), "")
        self.reiniciando = ""   # perfil al que se está cambiando (la consola avisa y espera)
        self._canal_cfg = cfg.get("canal") or {}
        self.canal = {"activo": bool(self._canal_cfg.get("auto", True)), "cada": self._canal_cfg.get("cada", [20, 45]),
                      "fuentes": [f for f in ("youtube", "twitch", "kick") if self._canal_cfg.get(f)]}
        self.canal_pend: list[dict] = []
        self.canal_vistos: dict[int, dict] = {}
        self._canal_i = -1
        self._canal_en_fila = False
        self._canal_ultimo = 0.0

    # --- eventos al navegador ------------------------------------------------------
    def emitir(self, ev: dict) -> None:
        if ev.get("type") in ("frase", "yo", "aviso", "dormida", "despierta", "fin", "biblioteca", "reflexion",
                              "canal", "canal_turno"):
            self.historial = (self.historial + [ev])[-200:]
        if ev.get("type") in ("frase", "fin"):
            self.ultima_actividad = time.monotonic()
        if ev.get("type") == "fin" and ev.get("doll") in self.dolls and ev.get("texto"):
            self._al_fin(ev)
        data = json.dumps(ev, ensure_ascii=False, default=str)
        for ws in list(self.clientes):
            if not ws.closed:
                asyncio.get_running_loop().create_task(ws.send_str(data))

    def info(self) -> dict:
        return {"type": "info", "ultima": self.ultima, "historial": self.historial, "sala": self.sala, "silencio": sorted(self.silencio),
                "sfw": bool(self.cfg.get("sfw")), "etiqueta": self.cfg.get("etiqueta") or {}, "canal": self.canal,
                "perfil": self.cfg.get("perfil", "habitual"),
                "perfiles": ["habitual", *(self.cfg.get("perfiles") or {})] if self.cfg.get("sfw") else [],
                "reiniciando": self.reiniciando,
                "voz": self.voz_actual, "voces": list(PRESETS) if self.cfg.get("perfil") == "ligero" else [],
                "escenas": [{k: e.get(k, "") for k in ("id", "label", "icono", "desc", "tempo", "baile")}
                            for e in self.escenas.values()],
                "baile_mmd": self.bailes.info(),
                "cola": self._estado_cola(), "conv": self.conv, "temas": self.cfg.get("temas_guion", []) + self.cfg.get("temas", []),  # temas_guion: solo en la lista, nunca solos
                "dolls": [{"id": d, "nombre": r.estado.nombre, "gestos": r.opciones.get("gestos", []),
                           "emociones": r.opciones.get("emociones", []), "estado": r.estado.__dict__,
                           "poses": r.opciones.get("poses", []), "bailes": r.opciones.get("bailes", {}),
                           "modos": self.modos.get(d, ["chat"]), "autonomia": self.autonomia.get(d, "off"),
                           "impulsos": self.impulsos.get(d, ["reflect", "research", "monologue", "lore"]),
                           "autonomias": self.autonomias.get(d, ["vida", "sleep"]),
                           "idioma_forzado": getattr(r, "_idioma_forzado", None),
                           "idioma_actual": getattr(r, "_idioma_usuario", r.idioma)}
                          for d, r in self.dolls.items()]}

    async def cambiar_voz(self, nombre: str) -> None:
        """Cambia la voz de todas en caliente (perfil ligero): gtts = CPU liviana; xtts = la voz de Joy, que usa GPU."""
        if nombre not in PRESETS or self.cfg.get("perfil") != "ligero":
            return self.aviso(None, f"voz no disponible: {nombre}")
        if nombre == self.voz_actual:
            return
        for did, r in self.dolls.items():
            r.voz = crear({**r.cfg.get("voz", {}), **PRESETS[nombre]}, self.cfg["xtts_url"],
                          avisar=lambda que, r=r: r._evento("aviso", texto="XTTS arrancando (~30 s): espero para hablar con su voz"))
        self.voz_actual = nombre
        xtts = next((x for x in (principal_xtts(r.voz) for r in self.dolls.values()) if x), None)
        if xtts:  # lo despierta y lo mantiene mientras haya charla (el orquestador lo apaga a los 2 min sin uso)
            asyncio.create_task(mantener_xtts(xtts, lambda: max(r.ultimo_turno for r in self.dolls.values()),
                                              activa=lambda: any(principal_xtts(r.voz) is xtts for r in self.dolls.values())))
        self.aviso(None, "voz: " + ("la de Joy (XTTS, usa GPU)" if nombre == "xtts" else "gTTS (CPU)"))
        self.emitir(self.info())

    async def cambiar_perfil(self, perfil: str) -> None:
        """Cambia entre el perfil habitual (Warudo, 4B, XTTS) y los de `perfiles:` (ligero). Cada perfil cambia el cerebro, la
        voz y las dolls que corren, así que reinicia todo (`dolls.sh restart`, aparte de este proceso, que también se apaga).
        Solo en modo SFW: el modo privado nunca usa Claude."""
        if not self.cfg.get("sfw"):
            return self.aviso(None, "el cambio de perfil es solo del modo stream (--sfw)")
        if perfil not in ("habitual", *(self.cfg.get("perfiles") or {})):
            return self.aviso(None, f"perfil desconocido: {perfil}")
        if perfil == self.cfg.get("perfil", "habitual"):
            return self.aviso(None, f"ya estás en el perfil {perfil}")
        if self.reiniciando:
            return
        self.reiniciando = perfil
        self.emitir(self.info())
        self.aviso(None, f"cambiando al perfil {perfil}: reinicio todo, vuelvo en ~20 s")
        flags = ["--sfw"] + ([] if perfil == "habitual" else [f"--{perfil}"])
        log_ = open(os.path.join(os.path.dirname(HERE), "logs", "reinicio.log"), "w")
        subprocess.Popen([os.path.join(os.path.dirname(HERE), "dolls.sh"), "restart", *flags], stdout=log_, stderr=log_,
                         stdin=subprocess.DEVNULL, start_new_session=True)

    def libres(self) -> list[str]:
        """Las dolls que maneja la IA (no están en modo marioneta)."""
        return [d for d, r in self.dolls.items() if not r.estado.titere]

    async def guion(self, texto: str, doll: str, escena_id: str, tempo=None) -> None:
        """Texto escrito por vos directo a la voz, con la escena. Entra en la fila con prioridad 0 (como tus mensajes)."""
        esc = self.escenas.get(escena_id)
        if not esc:
            return self.aviso(None, f"escena desconocida «{escena_id}»")
        segs = E.partir_guion(texto, {d: D.alias(d, r) for d, r in self.dolls.items()}, doll)
        if not segs:
            return self.aviso(None, "el guion está vacío")
        try:
            tempo = float(tempo) if tempo not in (None, "") else None
        except (TypeError, ValueError):
            tempo = None
        self.ultima_actividad = time.monotonic()
        self._cortar_sala()
        gid = self._guion_id = next(self._seq)

        async def fn():
            for d, t in segs:
                if self._guion_id != gid:  # callar / otro guion
                    break
                await self.dolls[d].leer(t, esc, tempo=tempo)
        quienes = ", ".join(dict.fromkeys(self.dolls[d].estado.nombre for d, _ in segs))
        await self.encolar(0, fn, f"guion «{esc.get('label', escena_id)}»: {quienes}")

    def aviso(self, doll, texto):
        self.emitir({"type": "aviso", "doll": doll, "texto": texto})

    # --- acciones que hablan (en fila, por prioridad) ----------------------------------
    def _estado_cola(self) -> dict:
        return {"type": "cola", "actual": self.actual, "pendientes": [e for _, e in sorted(self.en_fila.items())]}

    async def encolar(self, prio: int, fn, etiqueta: str, grupo: str = "") -> asyncio.Future:
        """grupo: "conv:<n>" (pasos de una conversación) o "sala:<n>"; se cancelan juntos (ver cancelar)."""
        seq = next(self._seq)
        fut = asyncio.get_running_loop().create_future()
        self.en_fila[prio * 10 ** 9 + seq] = etiqueta
        await self.cola.put((prio, seq, fn, etiqueta, fut, grupo))
        self.emitir(self._estado_cola())
        return fut

    def cancelar(self, pred) -> int:
        """Saca de la fila (y cancela) lo pendiente cuyo grupo cumpla pred. Lo que está sonando termina."""
        quedan, n = [], 0
        while not self.cola.empty():
            item = self.cola.get_nowait()
            prio, seq, _fn, _et, fut, grupo = item
            if pred(grupo):
                self.en_fila.pop(prio * 10 ** 9 + seq, None)
                if not fut.done():
                    fut.cancel()
                n += 1
            else:
                quedan.append(item)
        for item in quedan:
            self.cola.put_nowait(item)
        self.emitir(self._estado_cola())
        return n

    def cortar_charlas(self) -> None:
        """Termina las conversaciones y la sala en curso (sus pasos pendientes se descartan)."""
        self.conv["activa"] = False
        self._sala_id = next(self._seq)
        self.cancelar(lambda g: g.startswith(("conv:", "sala:")))

    def vaciar(self) -> None:
        self.cortar_charlas()
        self.cancelar(lambda g: True)

    async def turnos(self) -> None:
        while True:
            prio, seq, fn, etiqueta, fut, _grupo = await self.cola.get()
            self.en_fila.pop(prio * 10 ** 9 + seq, None)
            if fut.done():  # cancelada al vaciar
                continue
            self.actual = etiqueta
            self.emitir(self._estado_cola())
            try:
                await fn()
                if not fut.done():
                    fut.set_result(True)
            except Exception as e:  # noqa: BLE001
                log.exception("acción falló")
                self.aviso(None, f"error: {e}")
                if not fut.done():
                    fut.set_exception(e)
            self.actual = ""
            self.emitir(self._estado_cola())
            self.ultima_actividad = time.monotonic()

    async def poner_titere(self, doll: str, activo: bool) -> None:
        """Marioneta: la doll queda con su idle y su vida de fondo, pero la IA no le genera nada (ni respuestas, ni
        espontáneos, ni autonomía del agente, ni sala, ni chat del canal); lo que escribís lo dice ella."""
        r = self.dolls[doll]
        if activo and self.autonomia.get(doll, "off") != "off":  # los loops del agente (vida/sleep) se apagan
            ev = await r.cerebro.pedir({"cmd": "autonomia", "doll": doll, "modo": "off"})
            if ev.get("type") == "autonomia":
                self.autonomia[doll] = "off"
                self.emitir({"type": "autonomia", "doll": doll, "modo": "off"})
        if activo:
            self.cortar_charlas()
            self.cancelar(lambda g: g == "canal:")
        await r.poner_titere(activo)
        self.aviso(doll, f"{r.estado.nombre}: " + ("modo marioneta (la manejás vos; el idle sigue)" if activo
                                                    else "la IA vuelve a manejarla"))

    async def _mensaje_ambas(self, texto: str) -> None:
        """"Las dos": contesta una y después la otra al mismo mensaje (viendo lo que dijo la primera). Alternan."""
        ids = self.libres()
        if not ids:
            return
        self._ambas_i = (getattr(self, "_ambas_i", -1) + 1) % len(ids)
        orden = ids[self._ambas_i:] + ids[:self._ambas_i]
        for i, d in enumerate(orden):
            await self.dolls[d].turno(texto, self.usuario, tambien=i > 0)

    async def _mensaje(self, doll: str, texto: str) -> None:
        if self.dolls[doll].estado.titere:  # marioneta: lo que escribís es lo que dice (voz, cara y gestos de las señales)
            await self.dolls[doll].decir(texto, "titere")
            return
        await self.dolls[doll].turno(texto, self.usuario)
        otras = [d for d in self.libres() if d != doll]
        # con la sala prendida la otra ya replica sola (_al_fin); sin sala, a veces opina
        if otras and not self.sala["activo"] and random.random() < float(self.cfg.get("opinar", 0)):
            await self.dolls[random.choice(otras)].turno("", self.usuario, chime_in=True)

    async def _dialogo_sala(self, turnos: int, empieza: str) -> None:
        """Mini-diálogo de la sala autónoma: cada turno es un paso aparte (prioridad 3) y se corta en cuanto hacés
        algo (mensaje, botón, conversación con tema)."""
        ids = self.libres()
        if len(ids) < 2:
            return
        sala_id = self._sala_id = next(self._seq)
        vigente = lambda: self._sala_id == sala_id and self.sala["activo"]  # noqa: E731
        grupo = f"sala:{sala_id}"
        await self._paso(lambda: self.dolls[empieza].espontaneo("a_la_otra", self.usuario),
                         f"sala: {self.dolls[empieza].estado.nombre} le habla a la otra", grupo, 3)
        actual = empieza
        for _ in range(max(0, turnos - 1)):
            if not vigente():
                return
            actual = next(d for d in ids if d != actual)
            await self._paso(lambda a=actual: self.dolls[a].turno("", self.usuario, chime_in=True),
                             f"sala: {self.dolls[actual].estado.nombre} contesta", grupo, 3)

    # --- conversación con tema ----------------------------------------------------------
    async def _paso(self, fn, etiqueta: str, grupo: str = "conv:", prio: int = 2) -> None:
        try:
            await (await self.encolar(prio, fn, etiqueta, grupo))
        except asyncio.CancelledError:  # la cortaron (Parar, conversación nueva, vaciar): el llamador ve que no sigue
            pass
        except Exception as e:  # noqa: BLE001  (un paso que falla no corta la charla)
            log.warning("paso de la conversación falló: %s", e)

    async def _investigar(self, doll: str, tema: str, angulo: bool) -> None:
        r = self.dolls[doll]
        await r._cuerpo({"gesto": "pensar", "intensidad": 0.8})
        ev = await r.cerebro.pedir({"cmd": "investigar", "doll": doll, "tema": tema, "angulo": angulo})
        await r.cuerpo.enviar({"soltar": True})
        if ev.get("consulta") and ev.get("texto"):
            r._evento("biblioteca", consulta=ev["consulta"], nota=ev.get("nota", ""), texto=ev["texto"][:400])
        else:
            self.aviso(doll, f"no encontré nada para «{ev.get('consulta') or tema}»")

    async def _reflexionar(self, doll: str, tema: str) -> None:
        r = self.dolls[doll]
        await r._cuerpo({"gesto": "pensar", "intensidad": 0.8})
        ev = await r.cerebro.pedir({"cmd": "reflexionar", "doll": doll, "tema": tema})
        await r.cuerpo.enviar({"soltar": True})
        if ev.get("text"):
            r._evento("reflexion", tema=tema, texto=ev["text"][:1500])

    async def conversar(self, tema: str, turnos: int, investigar: bool, reflexionar: bool, empieza: str | None):
        """Charla sostenida entre las dolls sobre un tema: (investigan) → una abre → se contestan `turnos` veces (0 =
        hasta Parar), cada 4 turnos la que sigue vuelve a investigar para argumentar → (reflexionan al final)."""
        ids = self.libres()
        if not ids:
            self.aviso(None, "las dos están en modo marioneta: no hay quién charle")
            return
        tema = tema.strip() or random.choice(self.cfg.get("temas") or ["what's new with you"])
        self.cortar_charlas()  # una conversación nueva reemplaza a la anterior y a la sala (sin dejar pasos viejos)
        conv = self.conv = {"activa": True, "tema": tema, "turnos": turnos, "hechos": 0, "investigar": investigar,
                            "reflexionar": reflexionar}  # propio de ESTA conversación (otra nueva la reemplaza)
        vigente = lambda: self.conv is conv and conv["activa"]  # noqa: E731
        self.emitir({"type": "conv", "conv": conv})
        for r in self.dolls.values():  # hablan en el idioma del tema
            r._idioma_usuario = idioma(tema, getattr(r, "_idioma_usuario", r.idioma))
        try:
            if investigar:
                for i, d in enumerate(ids):
                    if not vigente():
                        return
                    await self._paso(lambda d=d, i=i: self._investigar(d, tema, angulo=i > 0),
                                     f"{self.dolls[d].estado.nombre} investiga «{tema}»")
            actual = empieza if empieza in self.dolls else random.choice(ids)
            if vigente():
                await self._paso(lambda a=actual: self.dolls[a].espontaneo("tema", self.usuario, tema=tema),
                                 f"{self.dolls[actual].estado.nombre} abre el tema")
                conv["hechos"] = 1
            while vigente() and (turnos <= 0 or conv["hechos"] < turnos) and len(ids) > 1:
                actual = next(d for d in ids if d != actual)
                if investigar and conv["hechos"] % 4 == 0:
                    await self._paso(lambda a=actual: self._investigar(a, tema, angulo=True),
                                     f"{self.dolls[actual].estado.nombre} busca argumentos")
                await self._paso(lambda a=actual: self.dolls[a].turno("", self.usuario, chime_in=True, tema=tema),
                                 f"{self.dolls[actual].estado.nombre} contesta ({conv['hechos'] + 1})")
                conv["hechos"] += 1
                self.emitir({"type": "conv", "conv": conv})
            # una sola doll (p. ej. el T-800 de anfitrión): sigue sola con el tema, con pausas para que entre el chat
            while vigente() and (turnos <= 0 or conv["hechos"] < turnos) and len(ids) == 1:
                await asyncio.sleep(4)
                if not vigente():
                    break
                await self._paso(lambda a=actual: self.dolls[a].espontaneo("tema_sigue", self.usuario, tema=tema),
                                 f"{self.dolls[actual].estado.nombre} sigue con el tema ({conv['hechos'] + 1})")
                conv["hechos"] += 1
                self.emitir({"type": "conv", "conv": conv})
            if reflexionar and conv.get("hechos") and self.conv is conv:
                for d in ids:
                    await self._paso(lambda d=d: self._reflexionar(d, tema),
                                     f"{self.dolls[d].estado.nombre} reflexiona")
        finally:
            conv["activa"] = False
            if self.conv is conv:
                self.emitir({"type": "conv", "conv": conv})

    async def _impulso(self, doll: str, impulso: str) -> None:
        if self.dolls[doll].estado.titere:
            return self.aviso(doll, f"{self.dolls[doll].estado.nombre} es marioneta: la manejás vos")
        self.aviso(doll, f"{self.dolls[doll].estado.nombre} {IMPULSO_AVISO.get(impulso, impulso)}…")
        await self.dolls[doll]._cuerpo({"gesto": "pensar", "intensidad": 0.8})
        r = await self.dolls[doll].cerebro.pedir({"cmd": "impulso", "doll": doll, "impulso": impulso})
        await self.dolls[doll].cuerpo.enviar({"soltar": True})
        texto = (r.get("text") or "").strip()
        if texto:
            await self.dolls[doll].decir(texto, impulso)
        else:
            self.aviso(doll, f"{impulso}: {r.get('resultado') or r.get('error') or 'sin resultado'}")

    def _cortar_sala(self) -> None:
        self._sala_id = next(self._seq)
        self.cadena = 0
        self.cancelar(lambda g: g.startswith("sala:"))

    # --- réplica: la otra le contesta en vez de seguir con lo suyo -----------------------
    POSTURAS = {"seguir": 0.35, "contradecir": 0.25, "preguntar": 0.2, "debatir": 0.2}

    def _al_fin(self, ev: dict) -> None:
        """Una doll terminó de hablar. Si no era una respuesta encadenada (o la cadena es corta), la otra le replica:
        le sigue el tema, la contradice, le repregunta o arma un debate. Solo con la sala autónoma prendida y sin
        conversación con tema (que ya alterna sola)."""
        d = ev["doll"]
        if str(ev.get("origen", "")).startswith("escena"):  # lo escribiste vos: la otra no le contesta sola
            return
        if self.silencio or self.dolls[d]._parar:  # en silencio (o si la acaban de callar) nadie replica sola
            return
        self.ultimo_habla = (d, time.monotonic())
        if self._en_replica:
            self.cadena += 1
        else:
            self.cadena = 1
        tirada = random.random()
        log.info("fin de %s · en_replica=%s cadena=%s sala=%s conv=%s tirada=%.2f", d, self._en_replica, self.cadena,
                    self.sala["activo"], self.conv.get("activa"), tirada)
        if (len(self.dolls) < 2 or not self.sala["activo"] or self.conv.get("activa")
                or self.cadena >= int(self.sala.get("dialogo_max", 5))
                or tirada > float(self.sala.get("replicar", 0.85))):
            return
        otra = next(x for x in self.dolls if x != d)
        if self.dolls[otra].estado.dormida or self.dolls[otra].estado.titere:
            return
        pesos = {**self.POSTURAS, **(self.sala.get("posturas") or {})}
        postura = random.choices(list(pesos), list(pesos.values()))[0]
        grupo = f"sala:{self._sala_id}"

        async def replica():
            self._en_replica = True
            try:
                await self.dolls[otra].turno("", self.usuario, chime_in=True, postura=postura)
            finally:
                self._en_replica = False
        asyncio.get_running_loop().create_task(self._paso(
            replica, f"{self.dolls[otra].estado.nombre} le replica a {self.dolls[d].estado.nombre} ({postura})",
            grupo, 3))

    def segmento(self, doll: str, texto: str, origen: str) -> None:
        """Segmento de autonomía (vida/dormir) que generó el agente. Si la otra acaba de hablar, se descarta: en vez
        de seguir con su guion, le contesta a la otra (la réplica ya está en fila o se pide ahora)."""
        if self.dolls[doll].estado.titere or self.silencio:  # el agente sigue con sus loops de fondo: lo que genere se descarta
            return
        otro, t = self.ultimo_habla
        if (len(self.dolls) > 1 and otro and otro != doll and time.monotonic() - t < 120
                and self.sala["activo"] and not self.conv.get("activa")):
            log.info("descarto el guion de %s (%s): le contesta a %s", doll, origen, otro)
            if not any(doll in e and "replica" in e for e in self.en_fila.values()):
                asyncio.get_running_loop().create_task(self._paso(
                    lambda: self.dolls[doll].turno("", self.usuario, chime_in=True, postura="seguir"),
                    f"{self.dolls[doll].estado.nombre} deja lo suyo y le replica a {self.dolls[otro].estado.nombre}",
                    f"sala:{self._sala_id}", 3))
            return
        asyncio.get_running_loop().create_task(self._paso(
            lambda: self.dolls[doll].decir(texto, origen), f"{self.dolls[doll].estado.nombre}: {origen}",
            f"sala:auto:{doll}", 3))

    # --- autonomía de la sala ----------------------------------------------------------
    def _alguien_habla(self) -> bool:
        return any(r.estado.hablando or r.estado.pensando or r.lock.locked() for r in self.dolls.values())

    def _vr_a_dolls(self) -> None:
        """Les pasa a las dolls si estás en el visor VR (y el video de la tele): el agente lo suma al prompt."""
        estado = {"nombre": self.usuario.get("nombre", "you"), "video": self.vr["video"] if titulo_legible(self.vr["video"]) else "",
                  "pista": self.vr["pista"], "playlist": self.vr["playlist"], "dormida": self.vr["dormida"],
                  "zona": self.vr["zona"], "evento": self.vr["evento"]} if self.vr["activo"] else None
        for r in self.dolls.values():
            r.vr = estado
            r.legajo = self.legajo.resumen if self.legajo else None

    def _hito(self, hito: str) -> None:
        if hito:
            log.info("legajo: hito «%s»", hito)
            self._trofeos.append(hito)

    async def sala_loop(self) -> None:
        """En los silencios hablan solas: un pensamiento, una pregunta para vos, o le hablan a la otra (y a veces se
        arma un mini-diálogo). El silencio que esperan es al azar dentro de `sala.silencio` (s)."""
        for r in self.dolls.values():  # el legajo también vale fuera del visor
            r.legajo = self.legajo.resumen if self.legajo else None
        espera = random.uniform(*self.sala["silencio"])
        while True:
            await asyncio.sleep(3)
            if (not self.sala["activo"] or self.silencio or self._alguien_habla() or not self.cola.empty() or self.actual
                    or self.conv.get("activa")):
                continue
            if any(r.estado.dormida for r in self.dolls.values()):
                continue
            if time.monotonic() - self.ultima_actividad < espera:
                continue
            espera = random.uniform(*self.sala["silencio"])
            ids = [d for d in self.libres() if self.autonomia.get(d, "off") == "off"]  # las que no están en vida/sleep
            if not ids:
                continue
            quien = random.choice(ids)
            if self.vr["activo"] and time.monotonic() - self.vr["visto"] > 90:  # el visor se cerró sin avisar
                self.vr.update(activo=False, video="", pista="", playlist="", dormida=False)
                self._vr_a_dolls()
            if self._trofeos and not self.vr["dormida"]:  # un hito del legajo: se lo entregan apenas hay un hueco
                hito = self._trofeos.pop(0)
                await self._paso(lambda q=quien, h=hito: self.dolls[q].espontaneo("trofeo", self.usuario, tema=h),
                                 f"sala: {self.dolls[quien].estado.nombre} te entrega un trofeo", f"sala:{self._sala_id}", 3)
                continue
            opciones = [("pensamiento", 0.2)]
            if not self.vr["activo"]:  # en el visor estás callada escuchando: nada que te pida contestar
                opciones += [("pregunta", 0.12), ("silencio", 0.05)]
            elif self.legajo:
                opciones.append(("mantra", 0.06))  # te susurra un mantra inventado (no tenés que repetirlo)
            if self.ocurrencias:
                opciones.append(("ocurrencia", 0.22))  # ideas que salen de la nada (el agente arma la chispa al azar)
            if titulo_legible(self.vr["video"]):  # con nombre random no hay nada que comentar
                opciones.append(("tele", 0.08))  # el video es de fondo: un comentario de vez en cuando
            if self.vr["pista"]:
                opciones.append(("audio", 0.1))  # lo que suena en BambiCloud (el título dice de qué trata)
            if len(self.dolls) > 1:
                opciones.append(("a_la_otra", 0.63))  # sobre todo charlan entre ellas
            elif self.cfg.get("temas"):
                opciones.append(("tema", 0.5))  # sola (anfitrión): saca uno de los temas del yaml
            pesos = (self.cfg.get("sala") or {}).get("pesos") or {}  # sala.pesos del yaml pisa los de arriba
            opciones = [(o, float(pesos.get(o, w))) for o, w in opciones]
            tipo = random.choices([o for o, _ in opciones], [w for _, w in opciones])[0]
            tema = random.choice(self.cfg["temas"]) if tipo == "tema" else ""
            promo = self.cfg.get("promo") or {}  # cada tanto, una doll anima el canal (seguir/suscribirse, de qué va)
            ahora = time.monotonic()
            if promo.get("activo", True) and promo and promo.get("doll", "joy") in ids:
                if not hasattr(self, "_promo_t"):
                    self._promo_espera = random.uniform(*promo.get("cada", [420, 720]))  # la primera, a los `primera` s
                    self._promo_t = ahora - self._promo_espera + random.uniform(*promo.get("primera", [60, 180]))
                if ahora - self._promo_t > self._promo_espera:
                    quien, tipo, tema = promo.get("doll", "joy"), "promo", ""
                    self._promo_t, self._promo_espera = ahora, random.uniform(*promo.get("cada", [420, 720]))
            # pensamientos/promo en varios idiomas (doll.idiomas_espontaneos: {es: 0.5, en: 0.25, ja: 0.25})
            idis = self.dolls[quien].cfg.get("idiomas_espontaneos") or {}
            lang = (random.choices(list(idis), [float(w) for w in idis.values()])[0]
                    if idis and tipo in ("pensamiento", "ocurrencia", "pregunta", "promo", "silencio") else "")
            # la sala solo ARRANCA algo; lo que sigue lo arman las réplicas (_al_fin): la otra le contesta
            await self._paso(lambda q=quien, t=tipo, te=tema, l=lang: self.dolls[q].espontaneo(t, self.usuario, tema=te,
                                                                                               idioma_turno=l),
                             f"sala: {self.dolls[quien].estado.nombre} ({tipo}{' ' + lang if lang else ''})",
                             f"sala:{self._sala_id}", 3)

    # --- chat del canal ------------------------------------------------------------------
    def chat_canal(self, autor: str, texto: str, plataforma: str = "chat") -> dict | None:
        """Entra un mensaje de un espectador. Se filtra (bots, comandos, palabras bloqueadas, links) y queda pendiente."""
        c = self._canal_cfg
        texto, quien = C.limpiar(texto), C.usuario(plataforma, autor)
        if texto.lower().startswith("!vivo"):  # en Twitch también vale «!vivo …», igual que en Discord
            texto = texto[5:].strip()
        if not texto or texto.startswith("!") or quien["nombre"].lower() in {str(x).lower() for x in c.get("ignorar", [])}:
            return None
        if any(str(p).lower() in texto.lower() for p in c.get("bloquear", []) if str(p).strip()):
            return None
        log.warning("chat %s · %s: %s", plataforma, quien["nombre"], texto[:120])  # se ve en el log aun sin -v
        m = {"id": next(self._seq), "autor": quien["nombre"], "usuario": quien, "texto": texto,
             "plataforma": plataforma, "t": time.monotonic()}
        self.canal_pend = (self.canal_pend + [m])[-40:]
        self.canal_vistos[m["id"]] = m
        for viejo in list(self.canal_vistos)[:-200]:
            del self.canal_vistos[viejo]
        self.emitir({"type": "canal", "id": m["id"], "autor": m["autor"], "texto": texto, "plataforma": plataforma})
        return m

    def _elegir_canal(self) -> dict:
        """Cuál contestan: el último que las nombra; si no, la última pregunta; si no, el último mensaje."""
        p = self.canal_pend
        return next((m for m in reversed(p) if D.nombrada(m["texto"], self.dolls)), None) or next(
            (m for m in reversed(p) if "?" in m["texto"]), p[-1])

    async def responder_canal(self, m: dict, doll: str | None = None) -> None:
        ids = [d for d in self.libres() if not self.dolls[d].estado.dormida] or self.libres()
        if not ids:  # todas en marioneta: el chat lo leés vos
            return
        if doll not in ids:
            doll = D.nombrada(m["texto"], {d: self.dolls[d] for d in ids})
        if doll not in ids:  # no nombró a ninguna: se turnan
            self._canal_i = (self._canal_i + 1) % len(ids)
            doll = ids[self._canal_i]
        self.canal_pend = [x for x in self.canal_pend if x["id"] != m["id"]]
        self._canal_en_fila = True

        async def fn():
            self.emitir({"type": "canal_turno", "id": m["id"], "doll": doll, "autor": m["autor"], "texto": m["texto"],
                         "plataforma": m["plataforma"]})
            origen = PLATAFORMAS.get(m["plataforma"])
            await self.dolls[doll].turno(f"[{m['autor']} en {origen}] {m['texto']}" if origen else m["texto"],
                                         m["usuario"], publico=True)

        def listo(f: asyncio.Future) -> None:
            self._canal_en_fila, self._canal_ultimo = False, time.monotonic()
            f.cancelled() or f.exception()
        fut = await self.encolar(1, fn, f"{self.dolls[doll].estado.nombre} le contesta a {m['autor']} (chat)", "canal:")
        fut.add_done_callback(listo)

    async def canal_loop(self) -> None:
        """Con el chat prendido, contesta un mensaje pendiente cada `canal.cada` segundos (los viejos se descartan)."""
        espera = 0.0
        while True:
            await asyncio.sleep(2)
            ahora, vence = time.monotonic(), float(self._canal_cfg.get("vence", 180))
            self.canal_pend = [m for m in self.canal_pend if ahora - m["t"] < vence]
            if (not self.canal["activo"] or not self.canal_pend or self._canal_en_fila
                    or ahora - self._canal_ultimo < espera):
                continue
            espera = random.uniform(*self.canal["cada"])
            await self.responder_canal(self._elegir_canal())

    async def api_relato(self, request: web.Request) -> web.Response:
        """Relator de partidos (director/relator.py). POST {"accion": "on"|"off", "tema"}: abre/cierra el partido (la sala
        se calla mientras); POST {"quien", "texto", "urgente"?}: la doll dice esa línea ya escrita. Sin «urgente», si
        alguien está hablando o hay fila, responde ocupado y no se encola (el relato viejo no sirve)."""
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "Content-Type: application/json"}, status=415)
        d = await request.json()
        if d.get("accion") == "on":
            self.conv = {"activa": True, "tema": d.get("tema") or "Partido", "turnos": 0, "hechos": 0,
                         "investigar": False, "reflexionar": False, "relato": True}
            self.emitir({"type": "conv", "conv": self.conv})
            return web.json_response({"ok": True})
        if d.get("accion") == "off":
            if self.conv.get("relato"):
                self.conv["activa"] = False
                self.emitir({"type": "conv", "conv": self.conv})
            return web.json_response({"ok": True})
        q, t = d.get("quien"), str(d.get("texto") or "").strip()
        if q not in self.dolls or not t or q not in self.libres():
            return web.json_response({"ok": False, "error": "doll no disponible"}, status=409)
        if not d.get("urgente") and (self._alguien_habla() or not self.cola.empty() or self.actual):
            return web.json_response({"ok": False, "error": "ocupada"}, status=409)
        await self.encolar(1, lambda: self.dolls[q].decir(t, "relato"), f"Relato: {self.dolls[q].estado.nombre}", "relato:")
        return web.json_response({"ok": True})

    async def api_canal(self, request: web.Request) -> web.Response:
        """POST {"autor", "texto", "plataforma"?}: otra fuente de chat (un bot propio, Discord...). El mensaje se trata
        igual que los de YouTube/Twitch: como de un espectador. Exige JSON (una página web ajena no puede mandarlo)."""
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "Content-Type: application/json"}, status=415)
        try:
            d = await request.json()
            m = self.chat_canal(str(d.get("autor") or "alguien"), str(d.get("texto") or ""),
                                str(d.get("plataforma") or "chat"))
        except (ValueError, AttributeError):
            return web.json_response({"ok": False, "error": "JSON inválido"}, status=400)
        return web.json_response({"ok": bool(m)})

    async def api_discord(self, request: web.Request) -> web.Response:
        """POST {"autor", "texto", "canal"?} con cabecera X-Joy-Token: un mensaje de Discord (el bot del VPS, por el
        túnel SSH inverso). Pasa delante del chat del canal y ESPERA el turno: devuelve {"ok", "texto"} con lo que la
        doll dijo en voz alta, para que el bot lo publique también como texto. Ver joy_discord.sh."""
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "Content-Type: application/json"}, status=415)
        token = os.environ.get("JOY_DISCORD_TOKEN", "")
        if not token or request.headers.get("X-Joy-Token") != token:
            return web.json_response({"ok": False, "error": "token"}, status=403)
        try:
            d = await request.json()
            texto = C.limpiar(str(d.get("texto") or ""))
            plat = str(d.get("plataforma") or "discord").lower()
            plat = plat if plat in PLATAFORMAS else "discord"
            sala_txt = re.sub(r"[^\w\s-]", "", str(d.get("canal") or ""))[:30].strip()
            quien = C.usuario(plat, str(d.get("autor") or "alguien"))
        except (ValueError, AttributeError):
            return web.json_response({"ok": False, "error": "JSON inválido"}, status=400)
        if not texto:
            return web.json_response({"ok": False, "error": "vacío"}, status=400)
        ids = [x for x in self.libres() if not self.dolls[x].estado.dormida] or self.libres()
        if not ids:
            return web.json_response({"ok": False, "error": "ocupada"}, status=503)
        doll = D.nombrada(texto, {x: self.dolls[x] for x in ids}) or ids[0]
        pendientes = sum(1 for k in self.en_fila if k < 10 ** 9)
        if pendientes >= 6:  # no apilar una fila de minutos: que reintenten después
            return web.json_response({"ok": False, "error": "fila", "fila": pendientes}, status=429)
        self.ultima_actividad = time.monotonic()
        self._cortar_sala()
        baile = await baile_overlay(texto)   # «Joy, ¿puedes bailar?» → baila de verdad y además contesta
        if baile:
            texto = f"{texto}\n(Nota: empiezas a bailar ahora mismo; coméntalo en una frase corta, sin inventar cómo lo haces.)"
        self.emitir({"type": "canal", "id": next(self._seq), "autor": quien["nombre"], "texto": texto,
                     "plataforma": plat})
        donde = PLATAFORMAS[plat] + (f" #{sala_txt}" if sala_txt else "")
        dicho: dict = {}

        async def fn():
            self.emitir({"type": "canal_turno", "id": 0, "doll": doll, "autor": quien["nombre"], "texto": texto,
                         "plataforma": plat})
            dicho["texto"] = await self.dolls[doll].turno(f"[{quien['nombre']} en {donde}] {texto}", quien,
                                                          publico=True)
        fut = await self.encolar(0, fn, f"{self.dolls[doll].estado.nombre} le contesta a {quien['nombre']} ({donde})",
                                 "discord:")
        try:
            await asyncio.wait_for(asyncio.shield(fut), 150)
        except asyncio.TimeoutError:
            return web.json_response({"ok": True, "texto": "", "pendiente": True})
        except Exception as e:  # cancelado (callar / vaciar fila) o error del turno
            return web.json_response({"ok": False, "error": type(e).__name__}, status=500)
        return web.json_response({"ok": True, "texto": dicho.get("texto", ""), "doll": self.dolls[doll].estado.nombre})

    # --- WebSocket -------------------------------------------------------------------
    def _doll(self, d) -> str | None:
        return d if d in self.dolls else None

    async def manejar(self, d: dict) -> None:
        t = d.get("type")
        doll = self._doll(d.get("doll"))
        if t == "msg" and d.get("text", "").strip() and d.get("doll") == "ambas" and len(self.dolls) > 1:
            texto = d["text"].strip()
            self.ultima_actividad = time.monotonic()
            self.emitir({"type": "yo", "doll": None, "texto": texto, "para": "las dos"})
            self._cortar_sala()
            await self.encolar(0, lambda: self._mensaje_ambas(texto), "las dos te contestan")
        elif t == "msg" and d.get("text", "").strip():
            texto = d["text"].strip()
            if not doll:
                doll, texto = D.destinataria(texto, self.dolls, self.ultima or next(iter(self.dolls)))
            self.ultima = doll
            self.ultima_actividad = time.monotonic()
            if not self.dolls[doll].estado.titere:  # a una marioneta no le "hablás": hablás por ella (sale su burbuja)
                self.emitir({"type": "yo", "doll": doll, "texto": texto})
            self._cortar_sala()
            titere = self.dolls[doll].estado.titere
            await self.encolar(0, lambda: self._mensaje(doll, texto),
                               f"{self.dolls[doll].estado.nombre} " + ("dice lo que escribís" if titere else "te contesta"))
        elif t == "vr":  # el visor VR: estás adentro (activo) y qué video pasa en la tele ("" = apagada)
            video = str(d.get("video") or "")[:160]
            pista, playlist = str(d.get("pista") or "")[:160], str(d.get("playlist") or "")[:120]
            nuevo = (titulo_legible(video) and video != self.vr["video"]) or (pista and pista != self.vr["pista"])
            dormida = bool(d.get("dormida"))
            if dormida != self.vr["dormida"]:
                log.info("visor VR: %s", "se durmió (siguen hablando, más suave)" if dormida else "despierta")
            self.vr.update(activo=bool(d.get("activo", True)), video=video, pista=pista, playlist=playlist,
                           dormida=dormida, zona=str(d.get("zona") or "")[:80], evento=str(d.get("evento") or "")[:160],
                           visto=time.monotonic())
            self._vr_a_dolls()
            if self.legajo and self.vr["activo"]:
                self._hito(self.legajo.noche())
            if nuevo and self.sala["activo"] and not self.silencio and random.random() < 0.3:  # a veces reaccionan a lo nuevo, no siempre
                self.ultima_actividad = min(self.ultima_actividad, time.monotonic() - 1000)
        elif t == "vr_escuchado" and self.legajo:  # terminó un archivo de BambiCloud (escuchado, no adelantado)
            self._hito(self.legajo.archivo(str(d.get("pista") or ""), float(d.get("segundos") or 0)))
        elif t == "escribiendo":
            self.ultima_actividad = time.monotonic()
            for r in ([self.dolls[doll]] if doll else self.dolls.values()):
                r.escuchar()
        elif t == "cuerpo" and doll:
            await self.dolls[doll]._cuerpo(d.get("intent") or {})
        elif t == "bailar":
            quienes = d.get("quienes")
            quienes = [x for x in self.dolls] if quienes == "ambas" else [x for x in (quienes or []) if x in self.dolls]
            con = d.get("con") or {}
            asyncio.create_task(self.bailes.bailar(str(d.get("baile")), quienes, bool(con.get("baile", True)),
                                                   bool(con.get("camara")), bool(con.get("musica", True))))
        elif t == "bailar_parar":
            asyncio.create_task(self.bailes.parar())
        elif t == "musica_sola":
            asyncio.create_task(self.bailes.musica_sola(str(d.get("baile"))))
        elif t == "guion":
            await self.guion(str(d.get("texto") or ""), doll or self.ultima or next(iter(self.dolls)),
                             str(d.get("escena") or "libre"), d.get("tempo"))
        elif t == "titere" and doll:
            await self.poner_titere(doll, bool(d.get("activo")))
        elif t == "reset" and doll:
            await self.dolls[doll].cuerpo.enviar({"reset": True, "soltar": True})
        elif t == "callar":  # corta lo que suena, lo que falta del turno (LLM y TTS) y todo lo que estaba en fila
            self.vaciar()
            self._guion_id = next(self._seq)
            for r in self.dolls.values():
                r.cancelar_lectura()
        elif t == "silencio":
            motivo = str(d.get("motivo") or "usuaria")[:20]
            if d.get("activo", True):
                self.silencio.add(motivo)
            else:
                self.silencio.discard(motivo)
            log.info("silencio: %s", sorted(self.silencio) or "no")
            self.emitir({"type": "silencio", "motivos": sorted(self.silencio)})
        elif t == "vaciar":
            self.vaciar()
        elif t == "conversar":
            if self._conv_task and not self._conv_task.done():
                self.conv["activa"] = False  # la anterior termina en su próximo paso
            self._conv_task = asyncio.create_task(self.conversar(
                str(d.get("tema") or ""), int(d.get("turnos") or 0), bool(d.get("investigar")),
                bool(d.get("reflexionar")), doll))
        elif t == "parar":
            self.cortar_charlas()
            self.emitir({"type": "conv", "conv": self.conv})
        elif t == "modo" and doll:
            r = await self.dolls[doll].cerebro.pedir({"cmd": "modo", "doll": doll, "user_id": self.usuario.get("id"),
                                                      "modo": d.get("modo")})
            if r.get("type") == "modo":
                self.dolls[doll].estado.modo = r["modo"]
                self.emitir({"type": "estado", "doll": doll, "estado": self.dolls[doll].estado.__dict__})
            else:
                self.aviso(doll, r.get("error", "no pude cambiar el modo"))
        elif t == "autonomia" and doll:
            if self.dolls[doll].estado.titere and d.get("modo") != "off":
                return self.aviso(doll, "es marioneta: apagá el modo marioneta para darle autonomía")
            r = await self.dolls[doll].cerebro.pedir({"cmd": "autonomia", "doll": doll, "modo": d.get("modo")})
            if r.get("type") == "autonomia":
                self.autonomia[doll] = r["modo"]
                self.emitir({"type": "autonomia", "doll": doll, "modo": r["modo"]})
            else:
                self.aviso(doll, r.get("error", "no pude cambiar la autonomía"))
        elif t == "sala":
            self.sala["activo"] = bool(d.get("activo"))
            self.ultima_actividad = time.monotonic()
            self.emitir({"type": "sala", "sala": self.sala})
        elif t == "voz":
            await self.cambiar_voz(str(d.get("voz", "")))
        elif t == "perfil":
            await self.cambiar_perfil(str(d.get("perfil", "")))
        elif t == "canal":
            self.canal["activo"] = bool(d.get("activo"))
            self.emitir({"type": "canal_estado", "canal": self.canal})
        elif t == "canal_responder" and d.get("id") in self.canal_vistos:
            await self.responder_canal(self.canal_vistos[d["id"]], doll)
        elif t == "espontaneo" and doll:
            if self.dolls[doll].estado.titere:
                return self.aviso(doll, "es marioneta: la manejás vos")
            await self.encolar(1, lambda: self.dolls[doll].espontaneo(str(d.get("tipo")), self.usuario),
                               f"{self.dolls[doll].estado.nombre}: {d.get('tipo')}")
        elif t == "dialogo":  # "charlen" sin tema: una conversación con un tema al azar (reemplaza la anterior)
            self._conv_task = asyncio.create_task(self.conversar("", int(d.get("turnos", 4)), False, False, doll))
        elif t == "impulso" and doll:
            if self.dolls[doll].estado.titere:
                return self.aviso(doll, "es marioneta: la manejás vos")
            await self.encolar(1, lambda: self._impulso(doll, str(d.get("impulso"))),
                               f"{self.dolls[doll].estado.nombre}: {d.get('impulso')}")
        elif t == "idioma":
            lang = d.get("lang")  # "en" | "es" | null (automático)
            targets = [doll] if doll else list(self.dolls)
            for did in targets:
                r = self.dolls[did]
                if lang:
                    r._idioma_usuario = lang
                    r._idioma_forzado = lang
                else:
                    r._idioma_forzado = None
                    r._idioma_usuario = r.idioma  # vuelve al default del yaml
                self.aviso(did, f"{r.estado.nombre}: idioma {'forzado a ' + lang if lang else 'automático'}")
            self.emitir({"type": "idioma", "doll": doll, "lang": lang})

    async def ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self.clientes.add(ws)
        await ws.send_str(json.dumps(self.info(), ensure_ascii=False, default=str))
        try:
            async for m in ws:
                if m.type == WSMsgType.TEXT:
                    try:
                        await self.manejar(json.loads(m.data))
                    except Exception as e:  # noqa: BLE001
                        log.exception("mensaje de la consola falló")
                        self.aviso(None, f"error: {e}")
        finally:
            self.clientes.discard(ws)
        return ws


async def main_async(args) -> None:
    cfg = D.cargar(args.config)
    w = Web(cfg)
    w.dolls = await D.armar(cfg, args.dolls.split(",") if args.dolls else None, emitir=w.emitir,
                            on_segmento=w.segmento)
    if not w.dolls:
        raise SystemExit("no hay dolls (¿está corriendo el agente y los joy_vmc?)")
    for did, r in w.dolls.items():
        info = await r.cerebro.pedir({"cmd": "modos", "doll": did})
        w.modos[did] = info.get("modos", ["chat"])
        w.autonomia[did] = info.get("autonomia", "off")
        w.impulsos[did] = info.get("impulsos", ["reflect", "research", "monologue", "lore"])
        w.autonomias[did] = info.get("autonomias", ["vida", "sleep"])
    for did in cfg.get("marioneta") or []:  # perfil ligero: BL4CKROSE la manejás vos hasta que la pases a IA (🎭)
        if did in w.dolls:
            await w.poner_titere(did, True)
    app = web.Application()
    app.router.add_get("/ws", w.ws)
    app.router.add_post("/api/canal", w.api_canal)
    app.router.add_post("/api/relato", w.api_relato)  # relator de partidos (director/relator.py)
    app.router.add_post("/api/discord", w.api_discord)  # el bot del VPS por el túnel (joy_discord.sh)
    app.router.add_get("/voz/{id}.wav", VW.servir)  # las voces para el visor VR del celular
    app.router.add_get("/", lambda r: web.FileResponse(os.path.join(HERE, "web", "index.html")))
    app.router.add_get("/subtitulos", lambda r: web.FileResponse(os.path.join(HERE, "web", "subtitulos.html")))
    app.router.add_get("/overlay", lambda r: web.FileResponse(os.path.join(HERE, "web", "overlay.html")))
    app.router.add_static("/img", os.path.join(HERE, "web", "img"))
    # 📺 BlackRose TV: parrilla de noticias (director/programacion.yaml) + overlay del logo
    pcfg = cfg.get("programacion") or {}
    w.programa = None
    if pcfg.get("archivo"):
        from .programacion import Programacion
        w.programa = Programacion(w, os.path.join(os.path.dirname(HERE), pcfg["archivo"]), bool(pcfg.get("activo", True)))

    async def api_programa(request: web.Request) -> web.Response:
        if not w.programa:
            return web.json_response({"ok": False, "error": "sin programación (programacion.archivo en el yaml)"})
        if request.method == "GET":
            return web.json_response(w.programa.info(), headers={"Cache-Control": "no-store"})
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "Content-Type: application/json"}, status=415)
        return web.json_response(w.programa.accion(await request.json()))
    app.router.add_get("/api/programa", api_programa)
    # la marquesina y el logo van aparte: director/blackrose_tv_srv.py (:8822, servicio brtv-overlay)
    app.router.add_post("/api/programa", api_programa)
    app.router.add_get("/blackrose_tv", lambda r: web.FileResponse(os.path.join(HERE, "web", "blackrose_tv.html")))
    for ruta in ("/charlita", "/empezamos"):  # overlay del stream: la misma página, dos escenas
        app.router.add_get(ruta, lambda r: web.FileResponse(os.path.join(HERE, "web", "charlita.html")))
    for ruta in ("/bimbo", "/bimbo-empezamos"):  # overlay del show 18+ (The Bimbo Dolls Show): misma página, otra marca
        app.router.add_get(ruta, lambda r: web.FileResponse(os.path.join(HERE, "web", "bimbo.html")))
    runner = web.AppRunner(app)
    await runner.setup()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    await web.TCPSite(runner, host, args.puerto).start()
    print(f"Consola: http://127.0.0.1:{args.puerto}   ·   subtítulos: /subtitulos   ·   overlay joystick: /overlay"
          "   ·   stream: /charlita y /empezamos",
          flush=True)
    asyncio.create_task(w.bailes.al_arrancar())  # si quedó un baile a medias, deja el VMC encendido
    asyncio.create_task(w.turnos())
    asyncio.create_task(w.sala_loop())
    asyncio.create_task(w.canal_loop())
    if w.programa:
        asyncio.create_task(w.programa.loop())
    w._lectores = C.lanzar(w._canal_cfg, w.chat_canal)  # YouTube/Twitch, si están configurados
    await asyncio.Event().wait()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--dolls")
    ap.add_argument("--puerto", type=int, default=8780)
    ap.add_argument("--lan", action="store_true", help="escuchar en la red local (celular)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
