"""proyecto.json: canal, estación (prompts), IA y la ficha creativa de cada integrante del reparto.

  <proyecto>/proyecto.json      este archivo (escritura atómica)
  <proyecto>/reparto/<id>.json  ficha técnica del VRM (la escribe reparto.py; aquí solo vive lo creativo)

Todo lo creativo viene vacío de fábrica: lo llena la persona en la pantalla Estación y en Mi Reparto.
Solo la instrucción técnica del formato de salida (ia.INSTRUCCION_FORMATO) es fija.

API (la registra servidor.py):
  GET   /api/proyecto                 proyecto completo
  PATCH /api/proyecto                 mezcla parcial por dentro (canal, estacion, ia) → proyecto validado
  GET   /api/reparto/{id}/perfil      rol, voz, idioma, personalidad, muletillas
  PATCH /api/reparto/{id}/perfil      mezcla parcial → perfil validado
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import tempfile

from aiohttp import web

log = logging.getLogger("studio.proyecto")

VERSION = 2
FORMATOS = ("noticias", "deportes", "panel", "entrevistas", "late_show", "documental")
ROLES = ("", "conductora", "panelista", "reportera", "invitada", "fondo")
MODOS_IA = ("local", "online", "manual")
MOTORES_VOZ = ("xtts",)                     # Piper/Edge llegarán como alternativas elegidas a mano, nunca automáticas
IDIOMAS = ("", "es", "en", "ja", "pt", "fr", "de", "it")
MAX_PROMPT = 20000
MAX_CORTO = 500
_ID = re.compile(r"^[a-z0-9_]{1,32}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_URL = re.compile(r"^https?://[^\s]{1,300}$")

PERFIL_DEF: dict = {
    "rol": "",
    "voz": {"voice": "", "temperatura": 0.75, "velocidad": 1.0, "tono": 1.0},
    "idioma": "",                            # vacío = el idioma del canal
    "personalidad": "",
    "muletillas": [],
}

PROYECTO_DEF: dict = {
    "version": VERSION,
    "canal": {"nombre": "", "lema": "", "logo": "",
              "colores": {"primario": "#ff2fd6", "secundario": "#00e5ff", "fondo": "#0b0716"},
              "tipografia": "", "idioma": "es"},
    "estacion": {"prompt_sistema": "", "directriz": "",
                 "formatos": {f: {"prompt": ""} for f in FORMATOS},
                 "apertura": "", "cierre": ""},
    "ia": {"modo": "local", "secuencial": True,
           "local": {"llm_url": "http://127.0.0.1:8087/v1/chat/completions", "modelo": "",
                     "antes_de_voz": "", "antes_de_guion": ""},
           "online": {"proveedor": "", "modelo": ""},
           "voz": {"motor": "xtts", "url": "http://127.0.0.1:9020/tts", "url_salud": ""}},
    "reparto": {},                           # id → perfil (PERFIL_DEF)
    "programas": [],
}


class ErrorProyecto(ValueError):
    pass


# ── validación ──
def _texto(v, ruta: str, maximo: int = MAX_CORTO) -> str:
    if not isinstance(v, str):
        raise ErrorProyecto(f"{ruta} debe ser texto")
    if len(v) > maximo:
        raise ErrorProyecto(f"{ruta}: máximo {maximo} caracteres")
    return v


def _num(v, ruta: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ErrorProyecto(f"{ruta}: número entre {lo} y {hi}")
    return float(v)


def _url(v, ruta: str, vacia: bool = False) -> str:
    _texto(v, ruta, 320)
    if not (vacia and v == "") and not _URL.match(v):
        raise ErrorProyecto(f"{ruta}: dirección http(s)://…")
    return v


def _uno_de(v, ruta: str, opciones) -> str:
    if v not in opciones:
        raise ErrorProyecto(f"{ruta}: {' | '.join(o or '(vacío)' for o in opciones)}")
    return v


def _solo(d, ruta: str, claves) -> dict:
    if not isinstance(d, dict):
        raise ErrorProyecto(f"{ruta} debe ser un objeto")
    fuera = set(d) - set(claves)
    if fuera:
        raise ErrorProyecto(f"{ruta}: claves desconocidas {sorted(fuera)}")
    return d


def validar_perfil(p: dict, ruta: str = "perfil") -> dict:
    _solo(p, ruta, PERFIL_DEF)
    _uno_de(p["rol"], f"{ruta}.rol", ROLES)
    v = _solo(p["voz"], f"{ruta}.voz", PERFIL_DEF["voz"])
    _texto(v["voice"], f"{ruta}.voz.voice", 120)
    if v["voice"] and not re.match(r"^[\w.\- ]+$", v["voice"]):
        raise ErrorProyecto(f"{ruta}.voz.voice: solo letras, números, espacio, punto, guion")
    _num(v["temperatura"], f"{ruta}.voz.temperatura", 0.05, 1.5)
    _num(v["velocidad"], f"{ruta}.voz.velocidad", 0.5, 2.0)
    _num(v["tono"], f"{ruta}.voz.tono", 0.5, 2.0)
    _uno_de(p["idioma"], f"{ruta}.idioma", IDIOMAS)
    _texto(p["personalidad"], f"{ruta}.personalidad", 4000)
    if not isinstance(p["muletillas"], list) or len(p["muletillas"]) > 30:
        raise ErrorProyecto(f"{ruta}.muletillas: lista de hasta 30")
    for i, m in enumerate(p["muletillas"]):
        _texto(m, f"{ruta}.muletillas[{i}]", 120)
    return p


def validar(p: dict) -> dict:
    """El proyecto completo (ya mezclado con los valores de fábrica)."""
    _solo(p, "proyecto", PROYECTO_DEF)
    if p["version"] != VERSION:
        raise ErrorProyecto(f"version debe ser {VERSION}")
    c = _solo(p["canal"], "canal", PROYECTO_DEF["canal"])
    for k in ("nombre", "lema", "tipografia"):
        _texto(c[k], f"canal.{k}", 80 if k != "lema" else 200)
    _texto(c["logo"], "canal.logo", 200)
    if c["logo"] and not re.match(r"^media/[\w.\-]+\.(png|jpg|jpeg|webp|svg)$", c["logo"]):
        raise ErrorProyecto("canal.logo: media/<archivo>.png|jpg|webp|svg")
    for k, v in _solo(c["colores"], "canal.colores", PROYECTO_DEF["canal"]["colores"]).items():
        if not isinstance(v, str) or not _COLOR.match(v):
            raise ErrorProyecto(f"canal.colores.{k}: #rrggbb")
    _uno_de(c["idioma"], "canal.idioma", IDIOMAS[1:])

    e = _solo(p["estacion"], "estacion", PROYECTO_DEF["estacion"])
    for k in ("prompt_sistema", "directriz", "apertura", "cierre"):
        _texto(e[k], f"estacion.{k}", MAX_PROMPT)
    for f, v in _solo(e["formatos"], "estacion.formatos", PROYECTO_DEF["estacion"]["formatos"]).items():
        _texto(_solo(v, f"estacion.formatos.{f}", ("prompt",))["prompt"], f"estacion.formatos.{f}.prompt", MAX_PROMPT)

    ia = _solo(p["ia"], "ia", PROYECTO_DEF["ia"])
    _uno_de(ia["modo"], "ia.modo", MODOS_IA)
    if not isinstance(ia["secuencial"], bool):
        raise ErrorProyecto("ia.secuencial: true | false")
    lo = _solo(ia["local"], "ia.local", PROYECTO_DEF["ia"]["local"])
    _url(lo["llm_url"], "ia.local.llm_url")
    _texto(lo["modelo"], "ia.local.modelo", 120)
    for k in ("antes_de_voz", "antes_de_guion"):
        _texto(lo[k], f"ia.local.{k}", MAX_CORTO)
        if "\n" in lo[k]:
            raise ErrorProyecto(f"ia.local.{k}: un solo comando, en una línea")
    on = _solo(ia["online"], "ia.online", PROYECTO_DEF["ia"]["online"])
    for k in ("proveedor", "modelo"):
        _texto(on[k], f"ia.online.{k}", 80)
    vz = _solo(ia["voz"], "ia.voz", PROYECTO_DEF["ia"]["voz"])
    _uno_de(vz["motor"], "ia.voz.motor", MOTORES_VOZ)
    _url(vz["url"], "ia.voz.url")
    _url(vz["url_salud"], "ia.voz.url_salud", vacia=True)

    if not isinstance(p["reparto"], dict):
        raise ErrorProyecto("reparto debe ser un objeto id → perfil")
    for rid, perfil in p["reparto"].items():
        if not _ID.match(rid):
            raise ErrorProyecto(f"reparto: id inválido {rid!r}")
        validar_perfil(perfil, f"reparto.{rid}")
    if not isinstance(p["programas"], list) or not all(isinstance(x, str) and len(x) < 200 for x in p["programas"]):
        raise ErrorProyecto("programas: lista de rutas")
    return p


# ── mezcla y migración ──
def mezclar(base: dict, parche: dict, ruta: str = "") -> dict:
    """Mezcla profunda: los objetos se mezclan por dentro, el resto se reemplaza. Claves ajenas → error."""
    out = copy.deepcopy(base)
    for k, v in parche.items():
        if k not in base:
            raise ErrorProyecto(f"{ruta + k}: clave desconocida")
        if isinstance(base[k], dict) and isinstance(v, dict) and not (ruta == "" and k == "reparto"):
            out[k] = mezclar(base[k], v, f"{ruta}{k}.")
        else:
            out[k] = copy.deepcopy(v)
    return out


def con_fabrica(d: dict, fabrica: dict) -> dict:
    """Rellena lo que falte con los valores de fábrica (sin tocar lo que hay)."""
    out = copy.deepcopy(fabrica)
    for k, v in d.items():
        if k in fabrica and isinstance(fabrica[k], dict) and isinstance(v, dict) and k != "reparto":
            out[k] = con_fabrica(v, fabrica[k])
        else:
            out[k] = v
    return out


def perfil_con_fabrica(p: dict) -> dict:
    return con_fabrica(p if isinstance(p, dict) else {}, PERFIL_DEF)


def migrar(d: dict) -> dict:
    """v1 (FASE0 §4: reparto como lista con vrm/miniatura/licencia y voz.motor por integrante) → v2."""
    if not isinstance(d, dict):
        raise ErrorProyecto("proyecto.json no es un objeto")
    v = d.get("version", 1)
    if v == 1:
        d = copy.deepcopy(d)
        rep = {}
        for r in d.get("reparto") or []:
            if not isinstance(r, dict) or not _ID.match(str(r.get("id", ""))):
                continue
            voz = {k: x for k, x in (r.get("voz") or {}).items() if k in PERFIL_DEF["voz"]}   # voz.motor pasa a ia.voz
            perfil = {k: r[k] for k in ("rol", "idioma", "personalidad", "muletillas") if k in r}
            perfil["voz"] = voz
            rep[r["id"]] = perfil_con_fabrica(perfil)
        d["reparto"] = rep
        d["version"] = 2
        log.info("proyecto.json migrado de v1 a v2")
    elif v != VERSION:
        raise ErrorProyecto(f"versión de proyecto desconocida: {v}")
    d = con_fabrica(d, PROYECTO_DEF)
    d["reparto"] = {k: perfil_con_fabrica(p) for k, p in d["reparto"].items()} if isinstance(d["reparto"], dict) else d["reparto"]
    return d


def escribir_atomico(ruta: str, obj) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        raise


class Proyecto:
    def __init__(self, carpeta: str, existe_vrm=lambda _id: True):
        self.dir = carpeta
        self.archivo = os.path.join(carpeta, "proyecto.json")
        self.existe_vrm = existe_vrm
        self.datos = self.cargar()

    def cargar(self) -> dict:
        try:
            with open(self.archivo, encoding="utf-8") as f:
                crudo = json.load(f)
            datos = validar(migrar(crudo))
        except FileNotFoundError:
            return copy.deepcopy(PROYECTO_DEF)
        except ValueError as e:                   # JSON roto o fuera del esquema (ErrorProyecto también es ValueError)
            # No se pisa: se aparta para que la persona no pierda lo que escribió.
            roto = self.archivo + ".roto"
            os.replace(self.archivo, roto)
            log.warning("proyecto.json inválido (%s); lo dejé en %s y arranco de fábrica", e, roto)
            return copy.deepcopy(PROYECTO_DEF)
        if crudo.get("version", 1) != VERSION:
            escribir_atomico(self.archivo, datos)
        return datos

    def guardar(self) -> None:
        escribir_atomico(self.archivo, self.datos)

    def cambiar(self, parche: dict) -> dict:
        if not isinstance(parche, dict):
            raise ErrorProyecto("se esperaba un objeto JSON")
        if set(parche) - {"canal", "estacion", "ia"}:
            raise ErrorProyecto("solo se pueden cambiar canal, estacion e ia (el reparto va por /api/reparto/<id>/perfil)")
        nuevo = validar(mezclar(self.datos, parche))
        self.datos = nuevo
        self.guardar()
        return nuevo

    def perfil(self, rid: str) -> dict:
        return copy.deepcopy(self.datos["reparto"].get(rid) or PERFIL_DEF)

    def cambiar_perfil(self, rid: str, parche: dict) -> dict:
        if not isinstance(parche, dict):
            raise ErrorProyecto("se esperaba un objeto JSON")
        if "muletillas" in parche and isinstance(parche["muletillas"], list):
            parche = {**parche, "muletillas": [m.strip() for m in parche["muletillas"] if isinstance(m, str) and m.strip()]}
        p = validar_perfil(mezclar(self.perfil(rid), parche), f"reparto.{rid}")
        self.datos["reparto"][rid] = p
        self.guardar()
        return p

    def olvidar(self, rid: str) -> None:
        if self.datos["reparto"].pop(rid, None) is not None:
            self.guardar()

    # ── rutas ──
    async def get(self, _req):
        return web.json_response(self.datos)

    async def patch(self, req: web.Request):
        try:
            return web.json_response(self.cambiar(await req.json()))
        except (ErrorProyecto, json.JSONDecodeError) as e:
            return web.json_response({"error": str(e)}, status=400)

    def _rid(self, req) -> str:
        rid = req.match_info["id"]
        if not _ID.match(rid) or not self.existe_vrm(rid):
            raise web.HTTPNotFound(text="no existe")
        return rid

    async def get_perfil(self, req):
        return web.json_response(self.perfil(self._rid(req)))

    async def patch_perfil(self, req):
        rid = self._rid(req)
        try:
            return web.json_response(self.cambiar_perfil(rid, await req.json()))
        except (ErrorProyecto, json.JSONDecodeError) as e:
            return web.json_response({"error": str(e)}, status=400)

    def registrar(self, r: web.UrlDispatcher) -> None:
        r.add_get("/api/proyecto", self.get)
        r.add_patch("/api/proyecto", self.patch)
        r.add_get("/api/reparto/{id}/perfil", self.get_perfil)
        r.add_patch("/api/reparto/{id}/perfil", self.patch_perfil)
