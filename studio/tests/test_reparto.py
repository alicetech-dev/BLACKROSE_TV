import aiohttp
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from studio.reparto import slug
from studio.servidor import crear_app
from studio.tests.fabrica_vrm import hacer_vrm, png


@pytest_asyncio.fixture
async def cli(tmp_path):
    c = TestClient(TestServer(crear_app(str(tmp_path))))
    await c.start_server()
    yield c
    await c.close()


def form(datos: bytes, nombre="avatar.vrm", optimizar=None):
    f = aiohttp.FormData()
    f.add_field("vrm", datos, filename=nombre, content_type="application/octet-stream")
    if optimizar is not None:
        f.add_field("optimizar", optimizar)
    return f


def test_slug():
    assert slug("Neko Gótica Látex") == "neko_gotica_latex"
    assert slug("¡!") == "avatar"


async def test_importar_listar_y_servir(cli, tmp_path):
    r = await cli.post("/api/reparto", data=form(hacer_vrm(nombre="Mi Neko")))
    assert r.status == 201
    f = await r.json()
    assert f["id"] == "mi_neko" and f["vrm"] == "/reparto/mi_neko.vrm" and f["miniatura"] == "/reparto/mi_neko.png"
    assert f["informe"]["ok"] and "texturas" not in f["informe"]
    assert (await cli.get(f["vrm"])).status == 200
    lista = await (await cli.get("/api/reparto")).json()
    assert [x["id"] for x in lista] == ["mi_neko"]
    # el mismo nombre otra vez no pisa el anterior
    r2 = await cli.post("/api/reparto", data=form(hacer_vrm(nombre="Mi Neko")))
    assert (await r2.json())["id"] == "mi_neko_2"


async def test_importar_optimiza_y_guarda_original(cli, tmp_path):
    r = await cli.post("/api/reparto", data=form(hacer_vrm(textura=(4096, 64))))
    f = await r.json()
    assert r.status == 201 and f["optimizado"]["texturas"] == 1
    assert "achicadas" in f["informe"]["avisos"][0] and not any("se pueden achicar" in a for a in f["informe"]["avisos"])
    assert (tmp_path / "reparto" / "originales" / f"{f['id']}.vrm").exists()


async def test_importar_sin_optimizar(cli, tmp_path):
    r = await cli.post("/api/reparto", data=form(hacer_vrm(textura=(4096, 64)), optimizar="0"))
    f = await r.json()
    assert f["optimizado"] is None and not (tmp_path / "reparto" / "originales" / f"{f['id']}.vrm").exists()


async def test_rechazos(cli):
    assert (await cli.post("/api/reparto", data=form(b"no soy un vrm"))).status == 422
    assert (await cli.post("/api/reparto", data=form(hacer_vrm(), nombre="x.exe"))).status == 400
    r = await cli.post("/api/reparto", data=form(hacer_vrm(huesos=["hips"])))
    assert r.status == 422 and "faltan huesos" in (await r.json())["errores"][0]
    assert (await cli.post("/api/reparto", json={})).status == 400


async def test_miniatura_y_borrado_limpia_escena(cli, tmp_path):
    f = await (await cli.post("/api/reparto", data=form(hacer_vrm(miniatura=False)))).json()
    assert f["miniatura"] is None
    assert (await cli.post(f"/api/reparto/{f['id']}/miniatura", data=b"GIF89a...")).status == 400
    grande = png(900, 900, ruido=True)                                  # varios trozos de red: debe llegar entera
    r = await cli.post(f"/api/reparto/{f['id']}/miniatura", data=grande)
    assert (await r.json())["miniatura"]
    assert (tmp_path / "reparto" / f"{f['id']}.png").read_bytes() == grande
    # usarlo en la escena, luego borrarlo: la escena vuelve a silueta
    rep = [{"id": "p1", "vrm": f["vrm"], "pos": "mesa_izq"}]
    assert (await cli.post("/api/escena", json={"reparto": rep})).status == 200
    assert (await cli.delete(f"/api/reparto/{f['id']}")).status == 200
    e = await (await cli.get("/api/escena")).json()
    assert e["reparto"][0]["vrm"] is None
    assert not any((tmp_path / "reparto").glob(f"{f['id']}.*"))


async def test_escena_rechaza_vrm_no_importado(cli):
    r = await cli.post("/api/escena", json={"reparto": [{"id": "p1", "vrm": "/reparto/fantasma.vrm"}]})
    assert r.status == 400


async def test_ids_invalidos(cli):
    assert (await cli.delete("/api/reparto/..%2Fescena")).status in (400, 404)
    assert (await cli.delete("/api/reparto/no_existe")).status == 404
