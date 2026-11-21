import io
import json
import wave

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from studio.ia import INSTRUCCION_FORMATO, solo_letras
from studio.proyecto import PROYECTO_DEF, VERSION, Proyecto, migrar, validar
from studio.servidor import crear_app
from studio.tests.fabrica_vrm import hacer_vrm

PLANTILLAS = __import__("pathlib").Path(__file__).resolve().parents[2] / "plantillas"


@pytest_asyncio.fixture
async def cli(tmp_path):
    c = TestClient(TestServer(crear_app(str(tmp_path))))
    await c.start_server()
    yield c
    await c.close()


async def importar(cli, nombre="Neko"):
    f = aiohttp.FormData()
    f.add_field("vrm", hacer_vrm(nombre=nombre), filename="a.vrm", content_type="application/octet-stream")
    return (await (await cli.post("/api/reparto", data=f)).json())["id"]


def wav_corto() -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(b"\0\0" * 2400)
    return b.getvalue()


@pytest_asyncio.fixture
async def falsos():
    """Un XTTS y un LLM de mentira: registran lo que reciben."""
    pedidos = {"tts": [], "models": 0, "chat": 0}
    modo = {"tts": "ok"}

    async def tts(req):
        pedidos["tts"].append(await req.json())
        if modo["tts"] == "ocupado":
            return web.Response(status=503, text="GPU ocupada")
        return web.Response(body=wav_corto(), content_type="audio/wav")

    async def models(_req):
        pedidos["models"] += 1
        return web.json_response({"data": [{"id": "qwen-4b"}]})

    async def chat(_req):
        pedidos["chat"] += 1
        return web.json_response({})

    app = web.Application()
    app.router.add_post("/tts", tts)
    app.router.add_get("/v1/models", models)
    app.router.add_post("/v1/chat/completions", chat)
    srv = TestServer(app)
    await srv.start_server()
    yield srv, pedidos, modo
    await srv.close()


# ── esquema ──
def test_fabrica_valida_y_sin_contenido():
    p = validar(json.loads(json.dumps(PROYECTO_DEF)))
    e = p["estacion"]
    assert e["prompt_sistema"] == e["directriz"] == e["apertura"] == e["cierre"] == ""
    assert all(v["prompt"] == "" for v in e["formatos"].values())
    assert p["canal"]["nombre"] == "" and p["reparto"] == {}
    assert p["ia"]["secuencial"] is True and p["ia"]["voz"]["motor"] == "xtts"
    assert p["ia"]["voz"]["url"].endswith(":9020/tts")


def test_plantilla_blackrose_valida_y_con_prompts_vacios():
    crudo = json.loads((PLANTILLAS / "blackrose" / "proyecto.json").read_text())
    p = validar(migrar(crudo))
    assert p["canal"]["nombre"]
    assert all(not v for k, v in p["estacion"].items() if k != "formatos")
    assert all(v["prompt"] == "" for v in p["estacion"]["formatos"].values())


def test_migrar_v1():
    v1 = {"version": 1, "canal": {"nombre": "Mi Canal", "idioma": "es"},
          "reparto": [{"id": "joy", "nombre": "Joy", "vrm": "reparto/joy.vrm", "rol": "conductora",
                       "voz": {"motor": "xtts", "voice": "joy", "temperatura": 0.6}, "personalidad": "curiosa",
                       "muletillas": ["nya"], "altura_m": 1.6, "licencia": {}}]}
    p = validar(migrar(v1))
    assert p["version"] == VERSION and p["canal"]["nombre"] == "Mi Canal"
    j = p["reparto"]["joy"]
    assert j["rol"] == "conductora" and j["voz"] == {"voice": "joy", "temperatura": 0.6, "velocidad": 1.0, "tono": 1.0}
    assert j["personalidad"] == "curiosa" and j["muletillas"] == ["nya"] and j["idioma"] == ""


def test_carga_migra_y_reescribe(tmp_path):
    (tmp_path / "proyecto.json").write_text(json.dumps({"version": 1, "reparto": []}))
    pj = Proyecto(str(tmp_path))
    assert pj.datos["version"] == VERSION
    assert json.loads((tmp_path / "proyecto.json").read_text())["version"] == VERSION


@pytest.mark.parametrize("malo", ["{roto", json.dumps({"version": 2, "inventada": 1}), json.dumps({"version": 99})])
def test_archivo_invalido_se_aparta_sin_borrarse(tmp_path, malo):
    (tmp_path / "proyecto.json").write_text(malo)
    pj = Proyecto(str(tmp_path))
    assert pj.datos["estacion"]["directriz"] == ""
    assert (tmp_path / "proyecto.json.roto").read_text() == malo


# ── API ──
async def test_patch_mezcla_y_persiste(cli, tmp_path):
    r = await cli.patch("/api/proyecto", json={"estacion": {"directriz": "Sé breve.", "formatos": {"noticias": {"prompt": "X"}}}})
    assert r.status == 200
    p = await r.json()
    assert p["estacion"]["directriz"] == "Sé breve." and p["estacion"]["formatos"]["noticias"]["prompt"] == "X"
    assert p["estacion"]["formatos"]["deportes"]["prompt"] == ""
    r = await cli.patch("/api/proyecto", json={"ia": {"local": {"modelo": "qwen"}}})
    p = await r.json()
    assert p["ia"]["local"]["modelo"] == "qwen" and p["ia"]["local"]["llm_url"].endswith("/chat/completions")
    guardado = json.loads((tmp_path / "proyecto.json").read_text())
    assert guardado["estacion"]["directriz"] == "Sé breve." and guardado["ia"]["local"]["modelo"] == "qwen"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("malo", [
    {"inventada": 1},
    {"version": 1},
    {"reparto": {}},
    {"estacion": {"otra": ""}},
    {"estacion": {"directriz": 5}},
    {"estacion": {"directriz": "x" * 20001}},
    {"ia": {"modo": "magia"}},
    {"ia": {"secuencial": "si"}},
    {"ia": {"local": {"llm_url": "ftp://x"}}},
    {"ia": {"local": {"antes_de_voz": "a\nb"}}},
    {"ia": {"voz": {"motor": "piper"}}},
    {"canal": {"colores": {"primario": "rojo"}}},
    {"canal": {"logo": "../../x.png"}},
    [],
])
async def test_patch_rechaza(cli, malo):
    r = await cli.patch("/api/proyecto", json=malo)
    assert r.status == 400 and "error" in await r.json()
    assert (await (await cli.get("/api/proyecto")).json())["estacion"]["directriz"] == ""


async def test_perfil_del_reparto(cli, tmp_path):
    rid = await importar(cli)
    p = await (await cli.get(f"/api/reparto/{rid}/perfil")).json()
    assert p["rol"] == "" and p["personalidad"] == "" and p["muletillas"] == [] and p["voz"]["voice"] == ""
    r = await cli.patch(f"/api/reparto/{rid}/perfil", json={"rol": "panelista", "voz": {"tono": 1.1},
                                                             "muletillas": [" nya ", "", "¿sabías?"]})
    p = await r.json()
    assert r.status == 200 and p["rol"] == "panelista" and p["voz"]["tono"] == 1.1 and p["voz"]["velocidad"] == 1.0
    assert p["muletillas"] == ["nya", "¿sabías?"]
    assert json.loads((tmp_path / "proyecto.json").read_text())["reparto"][rid]["rol"] == "panelista"
    for malo in ({"rol": "jefa"}, {"voz": {"velocidad": 9}}, {"voz": {"voice": "../x"}}, {"idioma": "xx"}, {"otra": 1}):
        assert (await cli.patch(f"/api/reparto/{rid}/perfil", json=malo)).status == 400, malo
    assert (await cli.get("/api/reparto/nadie/perfil")).status == 404
    # al quitar el VRM se olvida su ficha
    await cli.delete(f"/api/reparto/{rid}")
    assert rid not in (await (await cli.get("/api/proyecto")).json())["reparto"]


async def test_instruccion_fija(cli):
    d = await (await cli.get("/api/ia/instruccion")).json()
    assert d["texto"] == INSTRUCCION_FORMATO and '"lineas"' in d["texto"]


# ── salud y voz ──
async def test_probar_conexion_no_genera(cli, falsos):
    srv, pedidos, _ = falsos
    base = f"http://127.0.0.1:{srv.port}"
    await cli.patch("/api/proyecto", json={"ia": {"local": {"llm_url": base + "/v1/chat/completions"}, "voz": {"url": base + "/tts"}}})
    d = await (await cli.post("/api/ia/probar", json={"que": "llm"})).json()
    assert d["ok"] and d["estado"] == "listo" and "qwen-4b" in d["detalle"]
    d = await (await cli.post("/api/ia/probar", json={"que": "voz"})).json()
    assert d["ok"] and d["estado"] == "proxy"
    assert pedidos["chat"] == 0 and pedidos["tts"] == []            # ni una generación ni una síntesis
    assert (await cli.post("/api/ia/probar", json={"que": "otra"})).status == 400


async def test_probar_conexion_caida(cli, unused_tcp_port):
    muerto = f"http://127.0.0.1:{unused_tcp_port}"
    await cli.patch("/api/proyecto", json={"ia": {"local": {"llm_url": muerto + "/v1/chat/completions"}, "voz": {"url": muerto + "/tts"}}})
    for que in ("llm", "voz"):
        d = await (await cli.post("/api/ia/probar", json={"que": que})).json()
        assert not d["ok"] and d["estado"] == "no_responde"


async def test_probar_voz(cli, falsos):
    srv, pedidos, modo = falsos
    await cli.patch("/api/proyecto", json={"ia": {"voz": {"url": f"http://127.0.0.1:{srv.port}/tts"}}})
    rid = await importar(cli)
    await cli.patch(f"/api/reparto/{rid}/perfil", json={"idioma": "ja", "voz": {"voice": "mi_voz", "temperatura": 0.5}})
    r = await cli.post(f"/api/reparto/{rid}/probar_voz", json={"frase": "Hola, ¿qué tal?", "voz": {"velocidad": 1.2}})
    assert r.status == 200 and r.content_type == "audio/wav" and (await r.read())[:4] == b"RIFF"
    assert pedidos["tts"][-1] == {"text": "Hola ¿qué tal?", "language": "ja", "voice": "mi_voz", "temperature": 0.5, "speed": 1.2}
    # los sliders de prueba no se guardan
    assert (await (await cli.get(f"/api/reparto/{rid}/perfil")).json())["voz"]["velocidad"] == 1.0
    # sin frase no se inventa ninguna
    r = await cli.post(f"/api/reparto/{rid}/probar_voz", json={"frase": "  "})
    assert r.status == 400 and (await r.json())["codigo"] == "sin_frase"
    modo["tts"] = "ocupado"
    r = await cli.post(f"/api/reparto/{rid}/probar_voz", json={"frase": "hola"})
    assert r.status == 503 and (await r.json())["codigo"] == "ocupado"


async def test_probar_voz_sin_xtts(cli, unused_tcp_port):
    await cli.patch("/api/proyecto", json={"ia": {"voz": {"url": f"http://127.0.0.1:{unused_tcp_port}/tts"}}})
    rid = await importar(cli)
    r = await cli.post(f"/api/reparto/{rid}/probar_voz", json={"frase": "hola"})
    assert r.status == 502 and (await r.json())["codigo"] == "no_responde"


def test_solo_letras():
    assert solo_letras("¡Hola, mundo... (risas)!") == "¡Hola mundo risas !"
