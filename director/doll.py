"""Un turno de una doll, de punta a punta:

  mensaje → reacción inmediata (emoción transitoria del agente → cara + gesto, < 100 ms) → "pensar" en loop mientras
  el agente hace router/recuperar/pensar → stream del LLM → frases → por frase: señales (etiquetas, emoji, *acciones*)
  + síntesis (la N+1 mientras suena la N) → al empezar a sonar cada frase: emoción/gesto/mirada → RMS del bloque que
  suena → al terminar: ánimo persistente (necesidad dominante), suave.

Modo marioneta (`titere`): la doll no le pide nada al agente (turno/espontaneo devuelven ""), solo dice lo que le
mandan con `decir` y hace los gestos que le piden; el idle (joy_vmc) y `vivir` (miradas, gestos chicos) siguen.

Si el agente no responde (4B caído, el orquestador en el 35B/ComfyUI): la doll se duerme (gesto `dormida`) y se
revisa cada 20 s; al volver, se despierta sola (bostezo). No cae a Claude: la persona es adulta.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field

import httpx

from . import voz_web as VW
from .audio import Reproductor
from .clientes import Cerebro, Cuerpo
from .escenas import dividir
from .frases import Cortador
from .senales import Senales
from .voz import Voz, clean_for_speech, idioma

log = logging.getLogger("director.doll")


@dataclass
class Estado:
    doll: str
    nombre: str
    hablando: bool = False
    pensando: bool = False
    dormida: bool = False
    titere: bool = False  # la maneja una persona: la IA no genera respuestas, el idle y la vida de fondo siguen
    emocion: str = "neutral"
    gesto: str = ""
    animo: str = ""
    modo: str = "chat"
    escena: str = ""      # id de la escena del guion que está leyendo ("" = ninguna)
    pose: str = "parada"  # parada | sentada (la del joy_vmc; se cambia en caliente con el selector de la consola)
    baile: object = 0     # nivel 0..1 o nombre (suave | lento | fuerte | no) del último baile pedido
    voz: str = ""
    aviso: str = ""
    ultimo: dict = field(default_factory=dict)  # tiempos del último turno


class DollRunner:
    def __init__(self, doll: str, nombre: str, cerebro: Cerebro, cuerpo: Cuerpo, voz: Voz, repro: Reproductor,
                 cfg: dict, emitir=None):
        self.doll, self.cerebro, self.cuerpo, self.voz, self.repro, self.cfg = doll, cerebro, cuerpo, voz, repro, cfg
        self.estado = Estado(doll, nombre)
        self.senales: Senales | None = None
        self.opciones: dict = {}
        self.emitir = emitir or (lambda ev: None)  # eventos para la UI / subtítulos
        self.lock = asyncio.Lock()  # una doll habla de a un turno
        self.idioma = cfg.get("idioma", "en")
        self._vigia: asyncio.Task | None = None
        self.ultimo_turno = 0.0
        self.companeras: dict[str, "DollRunner"] = {}  # las otras dolls de la sala (para mirarlas cuando hablan)
        self._manos = False  # hablar_manos (loop) activo
        self._parar = False  # cancelar_lectura(): corta un guion en curso
        self._escuchando: asyncio.Task | None = None
        self.rng = random.Random()
        self.legajo = None  # () -> resumen del legajo de la operadora (lo pone la consola, solo en el modo privado)
        self.vr: dict | None = None  # {"nombre", "video"} mientras la operadora está en el visor VR (lo pone la consola)

    async def preparar(self) -> None:
        """Lee del joy_vmc de la doll qué emociones, gestos y miradas tiene (para el prompt y para validar)."""
        info = await self.cuerpo.enviar({"cmd": "listar"})
        if not info.get("ok"):
            log.warning("%s: joy_vmc no responde en %s; sigo sin cuerpo", self.doll, self.cuerpo.url)
            info = {"emociones": [], "gestos": {}}
        mirar = self.cfg.get("mirar") or ["camara", "izquierda", "derecha", "arriba", "abajo", "chat"]
        gestos = [g for g in info.get("gestos", {}) if g not in ("dormida",)]  # dormida la maneja el director
        self.opciones = {"emociones": info.get("emociones", []), "gestos": gestos, "mirar": mirar,
                         "cuerpo": self.cfg.get("cuerpo", ""), "poses": info.get("poses", []),
                         "bailes": info.get("bailes", {})}
        if info.get("ok"):  # en qué pose/baile está ahora (el joy_vmc puede haber arrancado con --pose sentada)
            est = await self.cuerpo.enviar({"cmd": "estado"})
            if est.get("ok"):
                self.estado.pose, self.estado.baile = est.get("pose", "parada"), est.get("baile", 0)
        validas = {k: self.opciones[k] for k in ("emociones", "gestos", "mirar")} if info.get("ok") else None
        self.senales = Senales.cargar(self.doll, validas)

    def _evento(self, tipo: str, **kw) -> None:
        self.emitir({"type": tipo, "doll": self.doll, **kw})

    async def _cuerpo(self, intent: dict) -> None:
        if intent:
            await self.cuerpo.enviar(intent)
            self.estado.emocion = intent.get("emocion", self.estado.emocion)
            self.estado.gesto = intent.get("gesto", self.estado.gesto)
            if "pose" in intent:
                self.estado.pose = intent["pose"]
                self.estado.baile = 0  # al cambiar de pose se corta el baile
            if "baile" in intent:
                self.estado.baile = intent["baile"] or 0
            self._evento("estado", estado=self.estado.__dict__)

    # --- turno ----------------------------------------------------------------
    async def poner_titere(self, activo: bool) -> None:
        """Prende/apaga el modo marioneta. Al prenderlo corta lo que estaba diciendo; el idle sigue."""
        est = self.estado
        est.titere = activo
        if activo:
            self.repro.callar()
            est.pensando = False
            if self._escuchando:
                self._escuchando.cancel()
            await self.cuerpo.enviar({"soltar": True})
        self._evento("estado", estado=est.__dict__)

    async def turno(self, texto: str, usuario: dict, *, chime_in: bool = False, room: str = "default",
                    tema: str = "", tambien: bool = False, postura: str = "", publico: bool = False) -> str:
        """tambien: contesta un mensaje que ya contestó la otra ("las dos"): lo ve y no lo repite.
        postura (con chime_in): seguir | contradecir | preguntar | debatir — cómo le contesta a la otra.
        publico: `usuario` es un espectador del chat del canal (no vos): el agente lo trata como tal."""
        if self.estado.titere:
            return ""
        async with self.lock:
            return await self._turno(texto, usuario, chime_in, room, tema=tema, tambien=tambien, postura=postura,
                                     publico=publico)

    async def espontaneo(self, tipo: str, usuario: dict, room: str = "default", tema: str = "", idioma_turno: str = "") -> str:
        """Habla sin que le escriban: pensamiento, a_la_otra, tema, pregunta, silencio (ver prompts.SPONTANEOUS)."""
        if self.estado.titere:
            return ""
        async with self.lock:
            return await self._turno("", usuario, False, room, espontaneo=tipo, tema=tema, idioma_turno=idioma_turno)

    async def decir(self, texto: str, origen: str = "") -> str:
        """Dice un texto ya escrito (segmentos de vida/sleep, monólogos del latido) con voz, cara y gestos."""
        async with self.lock:
            self._parar = False
            t0, tiempos, dicho = time.monotonic(), {}, []
            frases: asyncio.Queue = asyncio.Queue()
            cortador = Cortador(primera_max=10 ** 6, min_len=int(self.cfg.get("frase_min", 28)))
            for f in cortador.push(texto) + cortador.flush():
                frases.put_nowait((f, self.senales.modo(self.estado.modo)))
            frases.put_nowait(None)
            await self._hablar(frases, t0, tiempos, dicho)
            await self._cuerpo({"soltar": True})
            self._evento("fin", tiempos={k: round(v, 2) for k, v in tiempos.items()}, cache={}, texto=" ".join(dicho),
                         origen=origen)
            return " ".join(dicho)

    # --- guion: texto directo a la voz, con la animación de una escena -------------------
    def cancelar_lectura(self) -> None:
        """Corta el guion o el turno en curso: lo que suena se calla, lo que falta se descarta sin sintetizar y el
        pedido al agente se deja de leer (antes solo cortaba los guiones: un turno seguía con la frase siguiente)."""
        self._parar = True
        self.repro.callar()

    async def leer(self, texto: str, escena: dict, origen: str = "", tempo: float | None = None) -> str:
        """Lee `texto` tal cual (sin IA) con la escena: pose/baile/cara/mirada de la escena, pausas, manos. Al terminar
        deja la pose y el baile que tenía. Una doll lee de a un guion (el lock es el mismo que el de los turnos)."""
        async with self.lock:
            est = self.estado
            if est.dormida:
                await self.cuerpo.enviar({"soltar": True})
                est.dormida = False
            self._parar, est.escena = False, escena.get("id", "")
            antes = (est.pose, est.baile)
            try:
                await self._abrir_escena(escena, tempo)
                t0, tiempos, dicho = time.monotonic(), {}, []
                self._modo_cfg = {"gestos": escena.get("gestos", True), "mirar": escena.get("mirar"),
                                  **({"manos": escena["manos"]} if "manos" in escena else {})}
                frases: asyncio.Queue = asyncio.Queue()
                for parte in dividir(texto, escena):
                    frases.put_nowait({"pausa": parte} if isinstance(parte, float) else (parte, self._modo_cfg))
                frases.put_nowait(None)
                await self._hablar(frases, t0, tiempos, dicho)
            finally:
                self._modo_cfg = {}
                est.escena = ""
                await self._cerrar_escena(escena, antes)
            self._evento("fin", tiempos={k: round(v, 2) for k, v in tiempos.items()}, cache={}, texto=" ".join(dicho),
                         origen=origen or f"escena:{escena.get('id', '')}")
            return " ".join(dicho)

    async def _abrir_escena(self, escena: dict, tempo: float | None) -> None:
        est = self.estado
        baile = escena.get("baile")
        pose = escena.get("pose") or ("parada" if baile and est.pose != "parada" else None)
        if pose and pose != est.pose:
            await self._cuerpo({"pose": pose})
            await asyncio.sleep(1.5)  # el fundido de pose del joy_vmc
        intent = {k: escena[k] for k in ("emocion", "mirar") if escena.get(k)}
        if baile:
            intent.update(baile=baile, tempo=tempo or escena.get("tempo") or 72)
        if intent:
            await self._cuerpo(intent)

    async def _cerrar_escena(self, escena: dict, antes: tuple) -> None:
        pose, baile = antes
        intent: dict = {"soltar": True}
        if escena.get("emocion"):
            intent["emocion"] = "neutral"
        if escena.get("mirar"):
            intent["mirar"] = "camara"
        if escena.get("baile") or self.estado.baile:
            intent["baile"] = baile or "no"
        await self._cuerpo(intent)
        if self.estado.pose != pose:
            await self._cuerpo({"pose": pose})
            if baile:
                await asyncio.sleep(1.5)
                await self._cuerpo({"baile": baile})

    # --- vida: escuchar, mirar, idle ------------------------------------------------
    def escuchar(self) -> None:
        """Estás escribiendo: te mira y "escucha" (se suelta sola a los 8 s si no llega el mensaje)."""
        est = self.estado
        if est.hablando or est.pensando or est.dormida or est.titere or self.lock.locked():
            return
        if self._escuchando and not self._escuchando.done():
            return

        async def run():
            await self._cuerpo({"gesto": "escuchar", "intensidad": 0.7, "mirar": "camara"})
            await asyncio.sleep(8)
            if not self.lock.locked() and not est.hablando:
                await self.cuerpo.enviar({"soltar": True})
        self._escuchando = asyncio.create_task(run())

    async def mirar_a(self, otra: "DollRunner | None") -> None:
        """Mira a la compañera que habla (o vuelve a la cámara con None)."""
        if self.estado.hablando or self.estado.dormida:
            return
        destino = self.cfg.get("mirar_a", {}).get(otra.doll, "chat") if otra else "camara"
        await self.cuerpo.enviar({"mirar": destino})

    async def vivir(self) -> None:
        """Idle con intención: cada tanto mira a otro lado o hace un gesto chico (además de los tics de joy_vmc)."""
        miradas = ["camara", "camara", "camara", "chat", "izquierda", "derecha", "abajo", "arriba"]
        chicos = [g for g in ("ladear_cabeza", "asentir") if g in self.opciones.get("gestos", [])]
        while True:
            await asyncio.sleep(self.rng.uniform(5, 12))
            est = self.estado
            if est.hablando or est.pensando or est.dormida or self.lock.locked():
                continue
            if self.rng.random() < 0.8:
                await self.cuerpo.enviar({"mirar": self.rng.choice(miradas)})
            elif chicos:
                await self.cuerpo.enviar({"gesto": self.rng.choice(chicos), "intensidad": self.rng.uniform(0.3, 0.6)})

    def _vida_frase(self, intent: dict, voz: str, n: int, modo_cfg: dict) -> dict:
        """Movimiento mientras habla, cuando la frase no trae el suyo: manos, énfasis y mirada."""
        intent = dict(intent)
        gestos = self.opciones.get("gestos", [])
        sin_gestos = not modo_cfg.get("gestos", True)
        if "gesto" not in intent and not sin_gestos:
            fin = voz.rstrip()[-1:] if voz.strip() else ""
            if fin == "?" and "ladear_cabeza" in gestos and self.rng.random() < 0.6:
                intent["gesto"] = "ladear_cabeza"
                intent.setdefault("intensidad", 0.6)
            elif fin == "!" and "asentir" in gestos and self.rng.random() < 0.4:
                intent["gesto"] = "asentir"
                intent.setdefault("intensidad", 0.5)
            elif (not self._manos and "hablar_manos" in gestos and len(voz) > 25
                  and float(modo_cfg.get("manos", 1)) > 0):  # la escena puede bajarlas o sacarlas
                intent["gesto"] = "hablar_manos"
                intent.setdefault("intensidad", float(modo_cfg.get("manos", self.cfg.get("manos_intensidad", 0.45))))
        if "gesto" in intent:
            self._manos = intent["gesto"] == "hablar_manos"
        if "mirar" not in intent and not modo_cfg.get("mirar"):
            r = self.rng.random()
            otra = next(iter(self.companeras.values()), None)
            if n == 0 or r < 0.6:
                intent["mirar"] = "camara"
            elif r < 0.8 or not otra:
                intent["mirar"] = "chat"
            else:
                intent["mirar"] = self.cfg.get("mirar_a", {}).get(otra.doll, "chat")
        return intent

    async def _turno(self, texto, usuario, chime_in, room, espontaneo: str | None = None, tema: str = "",
                     tambien: bool = False, postura: str = "", publico: bool = False, idioma_turno: str = "") -> str:
        t0 = time.monotonic()
        tiempos: dict = {}
        est = self.estado
        self._parar = False  # un turno nuevo (callar corta el que estaba en curso)
        if est.dormida:  # le hablan dormida: se intenta igual (el mensaje puede levantar al 4B)
            await self.cuerpo.enviar({"soltar": True})
            est.dormida = False
        if texto.strip() and not getattr(self, "_idioma_forzado", None):
            self._idioma_usuario = idioma(texto, getattr(self, "_idioma_usuario", self.idioma))
        msg = {"doll": self.doll, "user_id": usuario.get("id", "doll_user"), "user_name": usuario.get("nombre", "you"),
               "room": room, "fast": bool(self.cfg.get("rapido", True)),
               "voice": {**self.opciones, "idioma": getattr(self, "_idioma_usuario", self.idioma),
                         "max_tokens": int(self.cfg.get("max_tokens", 160))}}
        self.ultimo_turno = time.monotonic()
        if idioma_turno:  # pensamiento/promo en otro idioma (es/en/ja), solo este turno
            msg["voice"]["idioma_turno"] = idioma_turno
        if tema:
            msg["tema"] = tema
        if tambien:
            msg["tambien"] = True
        if postura:
            msg["postura"] = postura
        if publico:
            msg["publico"] = True
        elif self.vr:  # la operadora está adentro del visor VR (y quizá mirando un video en la tele)
            msg["vr"] = self.vr
        if not publico and self.legajo and (leg := self.legajo()):
            msg["legajo"] = leg
        if espontaneo:
            msg["espontaneo"] = espontaneo
        elif chime_in:
            msg["chime_in"] = True
        else:
            msg["text"] = texto
        if self._escuchando:
            self._escuchando.cancel()
        cortador = Cortador(primera_max=int(self.cfg.get("primera_frase_max", 48)), min_len=int(self.cfg.get("frase_min", 28)))
        frases: asyncio.Queue = asyncio.Queue()
        dicho: list[str] = []
        pensar = asyncio.create_task(self._pensar_si_tarda(float(self.cfg.get("pensar_tras", 0.6))))
        hablar = asyncio.create_task(self._hablar(frases, t0, tiempos, dicho))
        modo_cfg: dict = {}
        cache: dict = {}
        enviadas = 0
        error = None
        try:
            async for ev in (evs := self.cerebro.eventos(msg)):
                if self._parar:  # 🔇: no se lee más del agente ni se encolan frases
                    break
                tipo = ev.get("type")
                if tipo == "reaction":
                    tiempos["reaccion"] = time.monotonic() - t0
                    if ev.get("exiting"):
                        self.repro.callar()
                        await self.cuerpo.enviar({"reset": True, "soltar": True})
                    elif not chime_in and not espontaneo:
                        await self._cuerpo(self.senales.reaccion(ev.get("emotion", "")))
                    est.animo = ev.get("mood", "")
                    self._animo_pend = (ev.get("need"), ev.get("energy"))
                elif tipo == "context":
                    tiempos["contexto"] = time.monotonic() - t0
                    est.modo = ev.get("mode", "chat")
                    modo_cfg = self._modo_cfg = self.senales.modo(est.modo)
                    if modo_cfg.get("mirar"):
                        await self.cuerpo.enviar({"mirar": modo_cfg["mirar"]})
                elif tipo == "delta":
                    tiempos.setdefault("primer_token", time.monotonic() - t0)
                    for f in cortador.push(ev["text"]):
                        frases.put_nowait((f, modo_cfg))
                        enviadas += 1
                elif tipo == "done":
                    cache = ev.get("cache") or {}
                    for f in cortador.flush():
                        # frase cortada por el tope de tokens ("You should've seen the way the"): no se dice
                        if enviadas and not re.search(r"[.!?…~)\]*\"'”]\s*$", f):
                            log.info("%s: descarto el final cortado %r", self.doll, f[-60:])
                            continue
                        frases.put_nowait((f, modo_cfg))
                    est.dormida = False
                elif tipo == "error":
                    error = ev
                    break
        finally:
            frases.put_nowait(None)
            pensar.cancel()
            await evs.aclose()  # cortado a la mitad: suelta la cola del pedido ya
        await hablar
        if error:
            await self._error(error)
            return ""
        need, energy = getattr(self, "_animo_pend", (None, None))
        await self._cuerpo({**self.senales.animo(need or "EQUILIBRIO", energy), "soltar": True})
        tiempos["total"] = time.monotonic() - t0
        est.ultimo = {k: round(v, 2) for k, v in tiempos.items()}
        self._evento("fin", tiempos=est.ultimo, cache=cache, texto=" ".join(dicho), origen=espontaneo or "")
        log.info("%s tiempos: %s", self.doll, est.ultimo)
        return " ".join(dicho)

    async def _pensar_si_tarda(self, espera: float) -> None:
        await asyncio.sleep(espera)
        if not self.estado.hablando:
            self.estado.pensando = True
            await self._cuerpo({"gesto": "pensar", "intensidad": 0.8})

    async def _hablar(self, frases: asyncio.Queue, t0: float, tiempos: dict, dicho: list[str]) -> None:
        """Consume frases: sintetiza la siguiente mientras suena la actual."""
        est = self.estado
        sintesis: asyncio.Queue = asyncio.Queue(maxsize=2)

        async def sintetizar():
            while (item := await frases.get()) is not None:
                if self._parar:  # guion cancelado: se vacía la cola sin sintetizar
                    continue
                if isinstance(item, dict):  # pausa del guion
                    await sintesis.put(item)
                    continue
                frase, modo_cfg = item
                visto, intent, fuentes = self.senales.frase(frase)  # lo que se lee en el chat y los subtítulos
                lang = idioma(visto, self.idioma)
                voz = clean_for_speech(visto, lang)  # lo que se sintetiza: solo texto pronunciable
                if not modo_cfg.get("gestos", True) and "gesto" in intent:
                    intent.pop("gesto")  # trance/spa: sin gestos
                if not any(ch.isalnum() for ch in voz):
                    await sintesis.put((visto, "", intent, None, 0))
                    continue
                ts = time.monotonic()
                try:
                    audio, sr = await self.voz.sintetizar(voz, lang)
                except Exception as e:  # noqa: BLE001  (una frase sin voz no corta el turno)
                    log.warning("%s: no pude sintetizar %r: %s", self.doll, voz[:40], e)
                    audio, sr = None, 0
                tiempos.setdefault("tts_primera", time.monotonic() - ts)
                est.voz = getattr(self.voz, "nombre", "")
                await sintesis.put((visto, voz, intent, audio, sr))
            await sintesis.put(None)

        prod = asyncio.create_task(sintetizar())
        n = 0
        self._manos = False
        try:
            while (item := await sintesis.get()) is not None:
                if self._parar:
                    break
                if isinstance(item, dict):
                    fin = time.monotonic() + item["pausa"]
                    while time.monotonic() < fin and not self._parar:
                        await asyncio.sleep(0.1)
                    continue
                visto, voz, intent, audio, sr = item
                if audio is None:
                    await self._cuerpo(intent)
                    if voz:  # sin voz (motor «mudo» o fallo del TTS): la frase igual cuenta como dicha y sale como subtítulo
                        dicho.append(visto)
                        est.hablando = True
                        self._evento("frase", texto=visto)
                        # tiempo de lectura: que el subtítulo quede en pantalla lo que tarda en leerse (lectura_cps)
                        cps = float(self.cfg.get("lectura_cps", 15))
                        fin = time.monotonic() + max(float(self.cfg.get("lectura_min", 2.5)), len(visto) / cps)
                        while time.monotonic() < fin and not self._parar:
                            await asyncio.sleep(0.1)
                    continue
                intent = self._vida_frase(intent, voz, n, getattr(self, "_modo_cfg", {}))
                if n == 0:
                    for c in self.companeras.values():
                        asyncio.get_running_loop().create_task(c.mirar_a(self))
                n += 1

                # en el visor VR la voz suena en el celular (voz_web): se baja ya y se le avisa cuándo arranca
                vid = VW.guardar(audio, sr, voz, idioma(voz, self.idioma), self.estado.doll) if self.vr is not None else ""
                if vid:
                    self._evento("voz", id=vid)

                def empieza(t, intent=intent, visto=visto, vid=vid):
                    if vid:  # t: instante (monotónico) en que sale por el DAC de la PC → reloj de pared
                        self._evento("voz_t", id=vid, t=round(time.time() + t - time.monotonic(), 3))
                    tiempos.setdefault("primer_audio", t - t0)
                    if est.pensando:
                        est.pensando = False
                        intent = {"soltar": True, **intent}
                    est.hablando = True
                    asyncio.get_running_loop().create_task(self._cuerpo(intent))
                    self._evento("frase", texto=visto)

                techo, piso = float(self.cfg.get("rms_techo", 0.2)), float(self.cfg.get("rms_piso", 0.01))
                await self.repro.decir(audio, sr, al_empezar=empieza,
                                       al_bloque=lambda t, v: self.cuerpo.rms(piso + v * (techo - piso)))
                dicho.append(visto)
        finally:
            est.hablando = False
            est.pensando = False  # un turno sin frases (vacío o todo filtrado) dejaba «pensando» y trababa la sala
            self._manos = False
            prod.cancel()
            if n:
                for c in self.companeras.values():
                    asyncio.get_running_loop().create_task(c.mirar_a(None))

    # --- dormida / despierta ----------------------------------------------------
    async def _error(self, ev: dict) -> None:
        est = self.estado
        if not ev.get("sleeping"):
            est.aviso = ev.get("error", "error")
            self._evento("aviso", texto=est.aviso)
            return
        est.dormida, est.aviso = True, "El 4B no responde: " + str(ev.get("error", ""))[:160]
        log.warning("%s se duerme: %s", self.doll, est.aviso)
        await self._cuerpo({"soltar": True, "emocion": "neutral"})
        await self.cuerpo.enviar({"gesto": "dormida"})
        self._evento("dormida", texto=est.aviso)
        if not self._vigia or self._vigia.done():
            self._vigia = asyncio.create_task(self._vigilar())

    async def _llm_arriba(self) -> bool:
        """Mira el llama-server DIRECTO (sin el proxy del orquestador): solo observa, no lo levanta ni le quita la GPU
        a otro cliente (35B, ComfyUI). Si está apagado por inactividad, el próximo mensaje lo levanta como siempre."""
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                return (await c.get(self.cfg.get("llm_directo", "http://127.0.0.1:8084") + "/health")).status_code == 200
        except httpx.HTTPError:
            return False

    async def _vigilar(self) -> None:
        while self.estado.dormida:
            await asyncio.sleep(20)
            if self.estado.dormida and await self._llm_arriba():
                self.estado.dormida, self.estado.aviso = False, ""
                await self.cuerpo.enviar({"soltar": True})
                await self._cuerpo({"gesto": "bostezo", "emocion": "feliz", "intensidad": 0.5})
                self._evento("despierta")
                return
