import io

import pytest
from PIL import Image

from studio import vrm as V
from studio.tests.fabrica_vrm import hacer_vrm


@pytest.mark.parametrize("version", ["1.0", "0.x"])
def test_vrm_valido(version):
    inf = V.analizar(hacer_vrm(version))
    assert inf["ok"] and inf["version"] == version
    assert inf["nombre"] == "Prueba" and inf["autores"] == ["tester"]
    assert len(inf["visemas"]) == 5 and inf["parpadeo"]
    assert inf["stats"]["triangulos"] == 1
    assert inf["miniatura_imagen"] == 1


def test_no_es_glb():
    with pytest.raises(V.VRMError, match="no es un archivo VRM"):
        V.analizar(b"hola mundo, esto no es un modelo")


def test_glb_sin_vrm():
    datos = V.escribir_glb({"asset": {"version": "2.0"}}, b"")
    with pytest.raises(V.VRMError, match="no un VRM"):
        V.analizar(datos)


def test_cortado():
    with pytest.raises(V.VRMError, match="cortado"):
        V.analizar(hacer_vrm()[:200])


def test_faltan_huesos_es_error():
    inf = V.analizar(hacer_vrm(huesos=["hips", "head"]))
    assert not inf["ok"] and "faltan huesos" in inf["errores"][0]


def test_avisos_boca_parpadeo_licencia():
    inf = V.analizar(hacer_vrm("0.x", visemas=False, parpadeo=False, permiso="onlyAuthor"))
    assert inf["ok"]
    texto = " ".join(inf["avisos"])
    assert "boca" in texto and "parpadeo" in texto and "solo su autora" in texto and "comercial" in texto


def test_miniatura_incrustada():
    d = hacer_vrm()
    png = V.miniatura(d, V.analizar(d))
    assert png and png.startswith(b"\x89PNG")


def test_optimizar_achica_texturas_y_conserva_geometria():
    d = hacer_vrm(textura=(4096, 64))
    inf = V.analizar(d)
    assert inf["stats"]["texturas_grandes"] == 1 and any("2048" in a for a in inf["avisos"])
    nuevo, n = V.optimizar(d)
    assert n == 1
    js0, bin0 = V.leer_glb(d)
    js1, bin1 = V.leer_glb(nuevo)
    # la geometría (vistas 0 y 1) queda idéntica byte a byte
    for iv in (0, 1):
        assert V._bytes_vista(js0, bin0, iv) == V._bytes_vista(js1, bin1, iv)
    with Image.open(io.BytesIO(V._bytes_vista(js1, bin1, 2))) as im:
        assert im.size == (2048, 32)
    assert all(v["byteOffset"] % 4 == 0 for v in js1["bufferViews"])
    assert V.analizar(nuevo)["ok"] and V.analizar(nuevo)["stats"]["texturas_grandes"] == 0


def test_optimizar_sin_cambios_devuelve_lo_mismo():
    d = hacer_vrm()
    assert V.optimizar(d) == (d, 0)
