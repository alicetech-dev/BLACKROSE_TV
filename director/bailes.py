"""Bailes MMD en Warudo: baile, cámara y canción por separado, para una muñeca o las dos.

Cada muñeca tiene su Reproductor MMD en Warudo (director/bailes.yaml). Para bailar:
  · se apaga su grafo "Seguimiento de pose - VMC" (si no, el VMC de joy_vmc pisa el baile) y se enciende el grafo
    "Pies fijos - MMD" (el IK de pies del VMD no se traduce bien a un esqueleto VRM);
  · se cargan baile / cámara / música en el reproductor según lo que pediste (cada cosa es opcional);
  · se da Play a todos juntos. Al terminar o al parar se deja todo como estaba.
La cámara y la música las maneja UNA sola muñeca (la primera) para no duplicarlas; la música sola y la cámara sola
también se pueden lanzar.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import yaml

from .cantante import Cantante
from .warudo import Warudo, WarudoError

log = logging.getLogger("director.bailes")
HERE = os.path.dirname(os.path.abspath(__file__))
MMD, MUSICA = "mmdmotion://data/MMD/", "audio://data/Music/"


def cargar(path: str | None = None) -> dict:
    with open(path or os.path.join(HERE, "bailes.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def ref(asset_id: str, nombre: str = "") -> dict:
    return {"id": asset_id, "name": nombre}


class Bailes:
    def __init__(self, cfg: dict, warudo: Warudo | None = None, emitir=None, path: str | None = None, cuerpos=None):
        self.w = warudo or Warudo()
        self.cuerpos = cuerpos or (lambda: {})  # () -> {doll: Cuerpo}: para que canten (boca con el audio, caras)
        self.cantante: Cantante | None = None
        self.path, self._mtime = path, 0.0  # con `path`, bailes.yaml se recarga solo al cambiar (sin reiniciar)
        self._aplicar(cfg)
        self.emitir = emitir or (lambda ev: None)
        self.actual: dict = {}
        self._vigia: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def _aplicar(self, cfg: dict) -> None:
        self.cfg = cfg
        self.bailes: dict[str, dict] = cfg.get("bailes") or {}
        wcfg = cfg.get("warudo") or {}
        self.jug: dict[str, dict] = wcfg.get("jugadores") or {}
        self.musica_id, self.camara_id = wcfg.get("musica"), wcfg.get("camara")

    def refrescar(self) -> None:
        """Si bailes.yaml cambió en disco, lo vuelve a leer (un yaml roto no pisa la config que anda)."""
        if not self.path:
            return
        try:
            m = os.path.getmtime(self.path)
            if m != self._mtime:
                nuevo = cargar(self.path)
                self._mtime = m
                self._aplicar(nuevo)
                log.info("bailes.yaml recargado")
        except (OSError, yaml.YAMLError) as e:
            log.warning("no pude recargar bailes.yaml: %s", e)

    # --- lo que ve la consola ---------------------------------------------------------------
    def info(self) -> dict:
        self.refrescar()
        return {"bailes": [{"id": i, "label": b.get("label", i), "duracion": b.get("duracion", 0), "loop": bool(b.get("loop")),
                            "credito": b.get("credito", ""), "camara": bool(b.get("camara")), "musica": bool(b.get("musica"))}
                           for i, b in self.bailes.items()],
                "con_player": [d for d, j in self.jug.items() if j.get("player")],
                "bailando": self.estado()}

    def estado(self) -> dict:
        a = self.actual
        if not a:
            return {}
        return {"baile": a["baile"], "quienes": a["quienes"], "con": a["con"],
                "pasaron": round(time.monotonic() - a["t0"], 1), "duracion": a["duracion"]}

    def _aviso(self, texto: str) -> None:
        self.emitir({"type": "aviso", "doll": None, "texto": texto})

    def _emitir_estado(self) -> None:
        self.emitir({"type": "bailando", "estado": self.estado()})

    # --- acciones -----------------------------------------------------------------------------
    async def bailar(self, baile: str, quienes: list[str], baile_on=True, camara=False, musica=True) -> bool:
        """quienes: ids de dolls. baile_on/camara/musica: qué lanzar (al menos una)."""
        self.refrescar()
        b = self.bailes.get(baile)
        if not b:
            self._aviso(f"baile desconocido «{baile}»")
            return False
        quienes = [d for d in quienes if d in self.jug]
        faltan = [d for d in quienes if not self.jug[d].get("player")]
        if faltan:
            self._aviso("sin Reproductor MMD en Warudo para: " + ", ".join(faltan) + " (ver director/bailes.yaml)")
            quienes = [d for d in quienes if d not in faltan]
        if not quienes or not (baile_on or camara or musica):
            self._aviso("elegí quién baila y qué lanzar (baile, cámara o música)")
            return False
        if musica and not baile_on and not camara:  # solo la canción: no hace falta el Reproductor MMD
            async with self._lock:
                await self._parar()
            await self.musica_sola(baile)
            return True
        async with self._lock:
            await self._parar()
            try:
                await self._preparar(b, quienes, baile_on, camara, musica)
            except WarudoError as e:
                self._aviso(f"Warudo: {e}")
                await self._restaurar(quienes)
                return False
            self.actual = {"baile": baile, "quienes": quienes, "con": {"baile": baile_on, "camara": camara, "musica": musica},
                           "t0": time.monotonic(), "duracion": 0 if b.get("loop") else float(b.get("duracion", 0)),
                           "loop": bool(b.get("loop"))}
            self._vigia = asyncio.create_task(self._vigilar())
        self._emitir_estado()
        return True

    async def _preparar(self, b: dict, quienes: list[str], baile_on: bool, camara: bool, musica: bool) -> None:
        w = self.w
        primera = quienes[0]
        for d in quienes:
            j = self.jug[d]
            if baile_on:
                for g in j.get("pose") or []:
                    await w.grafo(g, False)           # el VMC deja de pisar el cuerpo
                if j.get("pies"):
                    await w.grafo(j["pies"], True)
        for d in quienes:
            p = self.jug[d]["player"]
            await w.poner(p, "MotionVMDSource", MMD + b["baile"] if baile_on else None)
            await w.poner(p, "PlaybackLoop", bool(b.get("loop")))
            con_camara = d == primera and camara and b.get("camara")
            await w.poner(p, "CameraVMDSource", MMD + b["camara"] if con_camara else None)
            await w.poner(p, "Camera", ref(self.camara_id, "Cámara") if con_camara else None)
            con_musica = d == primera and musica and b.get("musica") and self.musica_id
            await w.poner(p, "MusicPlayer", ref(self.musica_id, "Reproductor de música") if con_musica else None)
            if con_musica:
                await w.poner(p, "MusicSource", MUSICA + b["musica"])
        await asyncio.gather(*(w.disparar(self.jug[d]["player"], "PlaybackPlay") for d in quienes))
        cuerpos = self.cuerpos()
        if baile_on and musica and b.get("musica") and any(d in cuerpos for d in quienes):
            self.cantante = Cantante({d: cuerpos[d] for d in quienes if d in cuerpos})
            await self.cantante.iniciar()

    async def musica_sola(self, baile: str) -> None:
        """Solo la canción (sin baile ni cámara), con el Reproductor de música."""
        b = self.bailes.get(baile)
        if not (b and b.get("musica") and self.musica_id):
            return self._aviso("ese baile no tiene canción o falta el Reproductor de música")
        await self.w.poner(self.musica_id, "Source", MUSICA + b["musica"])
        await self.w.disparar(self.musica_id, "PlaybackPlay")
        self._aviso(f"suena «{b.get('label', baile)}»")

    async def parar(self) -> None:
        async with self._lock:
            await self._parar()
        self._emitir_estado()

    async def _parar(self) -> None:
        if self._vigia:
            self._vigia.cancel()
            self._vigia = None
        if self.cantante:
            await self.cantante.parar()
            self.cantante = None
        quienes = list(self.actual.get("quienes") or [])
        self.actual = {}
        if not quienes and not self._conocidas():
            return
        await self._restaurar(quienes or self._conocidas())

    def _conocidas(self) -> list[str]:
        return [d for d, j in self.jug.items() if j.get("player")]

    async def _restaurar(self, quienes: list[str]) -> None:
        """Stop a los reproductores (y a la música), pose VMC otra vez encendido y pies fijos apagado."""
        w = self.w
        for d in quienes:
            j = self.jug.get(d) or {}
            for paso in (lambda: w.disparar(j["player"], "PlaybackStop") if j.get("player") else None,
                         # sin descargar el VMD, el reproductor sigue pisando el cuerpo con su primera pose
                         lambda: w.poner(j["player"], "MotionVMDSource", None) if j.get("player") else None,
                         lambda: w.grafo(j["pies"], False) if j.get("pies") else None,
                         *[(lambda g=g: w.grafo(g, True)) for g in j.get("pose") or []]):
                try:
                    c = paso()
                    if c:
                        await c
                except WarudoError as e:
                    log.warning("restaurar %s: %s", d, e)
        if self.musica_id:
            try:
                await w.disparar(self.musica_id, "PlaybackStop")
            except WarudoError:
                pass

    async def _vigilar(self) -> None:
        """Avisa a la consola cada tanto y restaura cuando termina el baile (los bailes en loop siguen hasta Parar)."""
        try:
            while self.actual:
                await asyncio.sleep(2)
                self._emitir_estado()
                a = self.actual
                if a and not a["loop"] and a["duracion"] and time.monotonic() - a["t0"] > a["duracion"] + 2:
                    log.info("terminó el baile %s", a["baile"])
                    async with self._lock:
                        await self._parar()
                    self._emitir_estado()
                    return
        except asyncio.CancelledError:
            pass

    async def al_arrancar(self) -> None:
        """Si el director murió con un baile en curso, deja el VMC encendido y los pies fijos apagados (best effort)."""
        try:
            await self._restaurar(self._conocidas())
        except (WarudoError, OSError) as e:
            log.info("Warudo no está listo, no se restauran los grafos: %s", e)
