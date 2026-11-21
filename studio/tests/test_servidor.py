import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from studio.servidor import ESCENA_DEF, crear_app, sets_disponibles


@pytest_asyncio.fixture
async def cli(tmp_path):
    c = TestClient(TestServer(crear_app(str(tmp_path))))
    await c.start_server()
    yield c
    await c.close()


def test_set_noticias_existe():
    assert "noticias" in sets_disponibles()


@pytest.mark.asyncio
async def test_escena_de_fabrica_sin_textos(cli):
    e = await (await cli.get("/api/escena")).json()
    assert e["set"] == "noticias"
    assert e["canal"] == "" and e["titular"] == ""          # nada de contenido de fábrica: lo pone la persona
    assert all(p["nombre"] == "" for p in e["reparto"])


@pytest.mark.asyncio
async def test_mezcla_luces_y_persiste(cli, tmp_path):
    r = await cli.post("/api/escena", json={"luces": {"key": 1.5}, "canal": "Mi Canal"})
    assert r.status == 200
    e = await r.json()
    assert e["luces"]["key"] == 1.5 and e["luces"]["fill"] == ESCENA_DEF["luces"]["fill"]
    guardada = json.loads((tmp_path / "escena.json").read_text())
    assert guardada["canal"] == "Mi Canal"
    # un servidor nuevo sobre el mismo proyecto la recupera
    c2 = TestClient(TestServer(crear_app(str(tmp_path))))
    await c2.start_server()
    try:
        assert (await (await c2.get("/api/escena")).json())["luces"]["key"] == 1.5
    finally:
        await c2.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("malo", [
    {"inventada": 1},
    {"set": "no_existe"},
    {"ambiente": "tarde"},
    {"luces": {"key": 9}},
    {"reparto": [{"id": "A B"}]},
    {"reparto": [{"id": "p1", "vrm": "/etc/passwd"}]},
    {"reparto": [{"id": "p1", "vrm": "/reparto/../x.vrm"}]},
])
async def test_rechaza_parches_invalidos(cli, malo):
    r = await cli.post("/api/escena", json=malo)
    assert r.status == 400


@pytest.mark.asyncio
async def test_ws_recibe_escena_y_cambios(cli):
    ws = await cli.ws_connect("/ws")
    primero = json.loads((await ws.receive()).data)
    assert primero["t"] == "escena"
    await cli.post("/api/plano", json={"plano": "grua"})
    m = json.loads((await ws.receive()).data)
    assert m == {"t": "plano", "plano": "grua"}
    await cli.post("/api/habla", json={"id": "p1", "on": True})
    m = json.loads((await ws.receive()).data)
    assert m == {"t": "habla", "id": "p1", "on": True}
    await ws.close()


@pytest.mark.asyncio
async def test_paginas_y_vendor(cli):
    for ruta in ("/estudio", "/salida", "/js/escena.js", "/js/sets/noticias.js", "/vendor/three.module.js", "/i18n/es.json"):
        assert (await cli.get(ruta)).status == 200, ruta


@pytest.mark.asyncio
async def test_static_no_escapa(cli):
    r = await cli.get("/reparto/..%2F..%2Fescena.json")
    assert r.status in (403, 404)
