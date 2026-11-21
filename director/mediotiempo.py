"""SHOW DE MEDIO TIEMPO de BlackRose TV: orquesta la parte con las dolls y la TANDA COMERCIAL 2049.

Lo sirve blackrose_tv_srv (:8822): la página /mediotiempo/ lee GET /api/mediotiempo y se dibuja sola.
  POST /api/mediotiempo {"accion":"iniciar"}            → cambia OBS a la escena «MEDIO TIEMPO», habla Joy/Kuroki, tanda de 10 min, y vuelve
                        {"accion":"iniciar","obs":false} → sin tocar OBS · {"accion":"iniciar","desde":"B"} → directo a la tanda
                        {"accion":"parar"}               → corta y vuelve a la escena de antes

Parte A (SEGS_A): las dolls hablan por `guion` del director (:8780/ws, voz edge + lipsync, CERO tokens) y la pantalla avanza cuando
terminan de decir cada línea (evento `fin`). Si el director no está, cada línea dura lo que se tarda en leerla.
Parte B: 10:00 exactos, reloj del servidor (inicioB); audio y animaciones los pone la página (guion.json de generar.py).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
import uuid

import aiohttp

log = logging.getLogger("mediotiempo")
HERE = os.path.dirname(os.path.abspath(__file__))
DIRECTOR_WS = os.environ.get("BRTV_DIRECTOR_WS", "ws://127.0.0.1:8780/ws")
OBS_CFG = os.path.expanduser("~/.var/app/com.obsproject.Studio/config/obs-studio/plugin_config/obs-websocket/config.json")
ESCENA = "MEDIO TIEMPO"
TOTAL_B = 600.0

# (id de pantalla, mínimo de segundos en pantalla, [(doll, texto), ...])
SEGS_A = [
    ("inicio", 14, [
        ("joy", "¡Atención, atención! Estamos en el medio tiempo, y esto es… ¡el Show de Medio Tiempo de BlackRose TV!"),
        ("kuroki", "¡Con redoble de batería incluido! Yo me encargo del ritmo, tú ponte cómodo."),
    ]),
    ("prog1", 14, [
        ("joy", "Primero, nuestra programación. En BlackRose TV tienes tecnología, deportes, noticias y economía, todos los días."),
        ("kuroki", "Tecnología sin humo. Deportes con opinión. Noticias sin filtro. Y economía, para entender qué pasa con tu bolsillo."),
    ]),
    ("prog2", 14, [
        ("joy", "Seguimos con inteligencia artificial, actualidad, debate e historia."),
        ("kuroki", "Sí: una inteligencia artificial hablando de inteligencia artificial. Y en el debate nos peleamos con cariño. Siempre con cariño."),
    ]),
    ("prog3", 14, [
        ("kuroki", "Documentales, conspiraciones, desarrollo de videojuegos y Linux. Las conspiraciones las analizamos con escepticismo: nada de sombreritos de aluminio."),
        ("joy", "Y Linux, con la terminal abierta, mucha cafeína y cero miedo a romper cosas."),
    ]),
    ("prog4", 14, [
        ("joy", "Y para cerrar la grilla: programación, vtubing, gaming y creaciones en tres D."),
        ("kuroki", "¡Todo lo que nos apasiona, en un solo canal! Y lo que no sabemos, lo aprendemos en vivo contigo."),
    ]),
    ("revolucion", 40, [
        ("joy", "Ahora, algo importante. Lo que estás viendo es una revolución tecnológica en las comunicaciones. "
                "Antes, para llegar a una audiencia necesitabas una antena, un estudio y un permiso. "
                "Hoy, con una computadora y una buena idea, puedes tener tu propio canal."),
        ("kuroki", "Con presentadoras de inteligencia artificial que conversan contigo en vivo, leen tu chat, cambian de idioma y no se cansan nunca."),
        ("joy", "Pasamos del telégrafo a la radio, de la radio a la televisión, de la televisión a internet… y ahora, a canales vivos que dialogan contigo."),
        ("kuroki", "O sea: la tele de siempre, pero que te contesta. Eso es BlackRose TV: televisión que escucha."),
    ]),
    ("suscribete", 20, [
        ("kuroki", "Y si quieres ser parte de esta revolución, hay un botón. Suscríbete al canal, activa la campanita y comparte BlackRose TV con alguien que todavía ve la tele muda."),
        ("joy", "Cada suscripción mantiene la señal encendida. Gracias por estar aquí, de verdad."),
    ]),
    ("tanda", 12, [
        ("joy", "Y ahora, la tanda comercial más larga del año: diez minutos de infomerciales de las corporaciones del año dos mil cuarenta y nueve. Todo ficticio, todo exagerado."),
        ("kuroki", "No te vayas. Volvemos en diez minutos, y mientras tanto, disfruta del futuro."),
    ]),
]


def _seg_estimada(texto: str) -> float:
    return 3.0 + len(texto.split()) / 2.3


class OBS:
    """Cambio de escena por obs-websocket (clave en el config del OBS flatpak). Cualquier fallo es silencioso: el show sigue."""

    def __init__(self) -> None:
        self.s: aiohttp.ClientSession | None = None
        self.ws = None

    async def conectar(self) -> bool:
        try:
            cfg = json.load(open(OBS_CFG))
            pw = cfg.get("server_password", "")
            self.s = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6))
            self.ws = await self.s.ws_connect(f"ws://127.0.0.1:{cfg.get('server_port', 4455)}", timeout=4)
            h = json.loads((await self.ws.receive()).data)
            d: dict = {"op": 1, "d": {"rpcVersion": 1, "eventSubscriptions": 0}}
            au = h["d"].get("authentication")
            if au:
                sec = base64.b64encode(hashlib.sha256((pw + au["salt"]).encode()).digest()).decode()
                d["d"]["authentication"] = base64.b64encode(hashlib.sha256((sec + au["challenge"]).encode()).digest()).decode()
            await self.ws.send_json(d)
            return json.loads((await self.ws.receive()).data)["op"] == 2
        except Exception as e:  # noqa: BLE001
            log.warning("OBS no responde: %s", e)
            await self.cerrar()
            return False

    async def pedir(self, tipo: str, datos: dict | None = None) -> dict:
        rid = uuid.uuid4().hex
        await self.ws.send_json({"op": 6, "d": {"requestType": tipo, "requestId": rid, "requestData": datos or {}}})
        while True:
            m = json.loads((await self.ws.receive()).data)
            if m["op"] == 7 and m["d"]["requestId"] == rid:
                return m["d"].get("responseData") or {}

    async def cerrar(self) -> None:
        try:
            if self.s:
                await self.s.close()
        finally:
            self.s = self.ws = None


class MedioTiempo:
    def __init__(self, guardar=lambda: None) -> None:
        self.est: dict = {"activo": False}
        self._tarea: asyncio.Task | None = None
        self._guardar = guardar

    def estado(self) -> dict:
        return {**self.est, "t": time.time(), "total_b": TOTAL_B}

    async def iniciar(self, obs: bool = True, desde: str = "A") -> dict:
        if self._tarea and not self._tarea.done():
            return {"ok": False, "error": "ya está en marcha (parar primero)"}
        self.est = {"activo": True, "fase": "A", "seg": None, "seg_t": time.time(), "inicioB": None, "obs": obs}
        self._tarea = asyncio.create_task(self._correr(obs, desde))
        return {"ok": True}

    async def parar(self) -> dict:
        if self._tarea and not self._tarea.done():
            self._tarea.cancel()
            try:
                await self._tarea
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        return {"ok": True}

    async def _correr(self, usar_obs: bool, desde: str) -> None:
        o = OBS()
        previa = None
        ses = aiohttp.ClientSession()
        ws = None
        cola: asyncio.Queue = asyncio.Queue()
        lector = None
        try:
            if usar_obs and await o.conectar():
                previa = (await o.pedir("GetCurrentProgramScene")).get("currentProgramSceneName")
                if previa != ESCENA:
                    await o.pedir("SetCurrentProgramScene", {"sceneName": ESCENA})
                else:
                    previa = None
            try:
                ws = await ses.ws_connect(DIRECTOR_WS, timeout=3)
                await ws.send_json({"type": "silencio", "activo": True, "motivo": "mediotiempo"})

                async def leer():
                    async for m in ws:
                        try:
                            ev = json.loads(m.data)
                        except (ValueError, TypeError):
                            continue
                        if ev.get("type") == "fin":
                            cola.put_nowait(ev.get("doll"))
                lector = asyncio.create_task(leer())
            except Exception as e:  # noqa: BLE001
                log.warning("director no responde (%s): las dolls no hablarán, la pantalla sigue por reloj", e)
                ws = None

            if desde != "B":
                for sid, minimo, lineas in SEGS_A:
                    self.est.update(seg=sid, seg_t=time.time())
                    t0 = time.monotonic()
                    for doll, texto in lineas:
                        while not cola.empty():
                            cola.get_nowait()
                        if ws is not None:
                            await ws.send_json({"type": "guion", "doll": doll, "texto": texto, "escena": "hablar"})
                            limite = 25 + _seg_estimada(texto) * 1.6
                            try:
                                while await asyncio.wait_for(cola.get(), limite) != doll:
                                    pass
                            except asyncio.TimeoutError:
                                log.warning("%s no terminó «%s…» a tiempo; sigo", doll, texto[:30])
                        else:
                            await asyncio.sleep(_seg_estimada(texto))
                        await asyncio.sleep(0.5)
                    resto = minimo - (time.monotonic() - t0)
                    if resto > 0:
                        await asyncio.sleep(resto)

            self.est.update(fase="B", seg=None, inicioB=time.time())
            await asyncio.sleep(TOTAL_B)
            self.est.update(fase="fin")
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("el show de medio tiempo se cayó")
        finally:
            self.est = {"activo": False}
            try:
                if ws is not None:
                    await ws.send_json({"type": "silencio", "activo": False, "motivo": "mediotiempo"})
                    await ws.close()
                if lector:
                    lector.cancel()
                await ses.close()
                if previa and o.ws is not None:
                    await o.pedir("SetCurrentProgramScene", {"sceneName": previa})
            except Exception as e:  # noqa: BLE001
                log.warning("limpieza: %s", e)
            await o.cerrar()
