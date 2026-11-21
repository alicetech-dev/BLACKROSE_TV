"""VRM sintéticos mínimos para las pruebas (no se versionan modelos reales: tienen licencia)."""
from __future__ import annotations

import io
import struct

from PIL import Image

from studio.vrm import HUESOS_REQ, escribir_glb


def png(w: int, h: int, color=(255, 0, 128, 255), ruido: bool = False) -> bytes:
    out = io.BytesIO()
    im = Image.effect_noise((w, h), 80).convert("RGBA") if ruido else Image.new("RGBA", (w, h), color)
    im.save(out, "PNG")
    return out.getvalue()


def hacer_vrm(version: str = "1.0", huesos=HUESOS_REQ, visemas=True, parpadeo=True, textura=(64, 64),
              nombre: str = "Prueba", permiso: str = "everyone", miniatura: bool = True) -> bytes:
    # geometría: 1 triángulo (3 índices uint16) en su propia vista, luego la textura y (opcional) la miniatura
    indices = struct.pack("<3H", 0, 1, 2) + b"\x00\x00"
    posiciones = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    tex = png(*textura)
    vistas, binario = [], b""
    for b in (indices, posiciones, tex) + ((png(32, 32, (0, 200, 255, 255)),) if miniatura else ()):
        binario += b"\x00" * (-len(binario) % 4)
        vistas.append({"buffer": 0, "byteOffset": len(binario), "byteLength": len(b)})
        binario += b
    js = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binario)}],
        "bufferViews": vistas,
        "accessors": [{"bufferView": 0, "componentType": 5123, "count": 3, "type": "SCALAR"},
                      {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 1}, "indices": 0}]}],
        "images": [{"bufferView": 2, "mimeType": "image/png"}] + ([{"bufferView": 3, "mimeType": "image/png"}] if miniatura else []),
        "textures": [{"source": 0}] + ([{"source": 1}] if miniatura else []),
        "materials": [{"name": "m"}],
        "extensions": {},
    }
    if version == "1.0":
        exprs = {k: {} for k in (["aa", "ih", "ou", "ee", "oh"] if visemas else [])}
        if parpadeo:
            exprs["blink"] = {}
        meta = {"name": nombre, "authors": ["tester"], "avatarPermission": permiso, "commercialUsage": "corporation", "licenseUrl": "https://example.org"}
        if miniatura:
            meta["thumbnailImage"] = 1
        js["extensions"]["VRMC_vrm"] = {"specVersion": "1.0", "meta": meta,
                                         "humanoid": {"humanBones": {h: {"node": 0} for h in huesos}},
                                         "expressions": {"preset": exprs}}
    else:
        grupos = [{"presetName": p} for p in (["a", "i", "u", "e", "o"] if visemas else [])] + ([{"presetName": "blink"}] if parpadeo else [])
        meta = {"title": nombre, "author": "tester", "allowedUserName": "OnlyAuthor" if permiso == "onlyAuthor" else "Everyone",
                "commercialUssageName": "Disallow", "licenseName": "CC_BY"}
        if miniatura:
            meta["texture"] = 1
        js["extensions"]["VRM"] = {"meta": meta, "humanoid": {"humanBones": [{"bone": h, "node": 0} for h in huesos]},
                                    "blendShapeMaster": {"blendShapeGroups": grupos}}
    return escribir_glb(js, binario)
