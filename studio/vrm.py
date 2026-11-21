"""Importar un VRM (0.x o 1.0): leer el GLB, validarlo, resumir licencia y avisos, y achicar texturas enormes.

  python -m studio.vrm archivo.vrm            # imprime el informe
  python -m studio.vrm archivo.vrm --optimizar salida.vrm

Nada sale de la PC: el archivo se lee y se reescribe localmente.
El informe distingue **errores** (no se puede usar) de **avisos** (se puede, pero conviene saberlo).
"""
from __future__ import annotations

import io
import json
import struct
import sys

MAGIA, CHUNK_JSON, CHUNK_BIN = b"glTF", 0x4E4F534A, 0x004E4942
MAX_ARCHIVO = 300 * 1024 * 1024
LADO_MAX = 2048                       # lado de textura a partir del cual se achica
AVISO_ARCHIVO = 60 * 1024 * 1024
AVISO_TRIANGULOS = 120_000
AVISO_VRAM_TEX = 256 * 1024 * 1024   # memoria estimada de texturas (RGBA sin comprimir)

HUESOS_REQ = ["hips", "spine", "head", "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm", "rightLowerArm", "rightHand",
              "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot"]
VISEMAS_0, VISEMAS_1 = ["a", "i", "u", "e", "o"], ["aa", "ih", "ou", "ee", "oh"]


class VRMError(ValueError):
    pass


def leer_glb(datos: bytes) -> tuple[dict, bytes]:
    if len(datos) < 20:
        raise VRMError("el archivo está vacío o cortado")
    magia, version, largo = struct.unpack_from("<4sII", datos, 0)
    if magia != MAGIA:
        raise VRMError("no es un archivo VRM/GLB (cabecera glTF ausente)")
    if version != 2:
        raise VRMError(f"glTF versión {version}; se necesita 2")
    if largo > len(datos):
        raise VRMError("el archivo está cortado (descarga incompleta)")
    js, binario, pos = None, b"", 12
    while pos + 8 <= largo:
        n, tipo = struct.unpack_from("<II", datos, pos)
        cuerpo = datos[pos + 8: pos + 8 + n]
        if tipo == CHUNK_JSON and js is None:
            try:
                js = json.loads(cuerpo.decode("utf-8").rstrip(" \x00"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise VRMError(f"JSON interno dañado: {e}") from e
        elif tipo == CHUNK_BIN and not binario:
            binario = bytes(cuerpo)
        pos += 8 + n
    if js is None:
        raise VRMError("falta el bloque JSON del glTF")
    return js, binario


def escribir_glb(js: dict, binario: bytes) -> bytes:
    j = json.dumps(js, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    j += b" " * (-len(j) % 4)
    b = binario + b"\x00" * (-len(binario) % 4)
    total = 12 + 8 + len(j) + (8 + len(b) if b else 0)
    out = struct.pack("<4sII", MAGIA, 2, total) + struct.pack("<II", len(j), CHUNK_JSON) + j
    if b:
        out += struct.pack("<II", len(b), CHUNK_BIN) + b
    return out


def _bytes_vista(js: dict, binario: bytes, iv: int) -> bytes:
    v = js["bufferViews"][iv]
    if v.get("buffer", 0) != 0:
        raise VRMError("buffers externos no soportados")
    ini = v.get("byteOffset", 0)
    return binario[ini: ini + v["byteLength"]]


def _imagen(js, binario, img: dict) -> tuple[bytes | None, str]:
    if "bufferView" in img:
        return _bytes_vista(js, binario, img["bufferView"]), img.get("mimeType", "")
    return None, img.get("mimeType", "")            # URI externa o data: (no habitual en VRM)


def _tamano_imagen(datos: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(datos)) as im:
            return im.size
    except Exception:  # noqa: BLE001 — imagen rara: no bloquea, solo no se mide
        return None


def _triangulos(js: dict) -> int:
    t = 0
    for m in js.get("meshes", []):
        for p in m.get("primitives", []):
            if p.get("mode", 4) != 4:
                continue
            acc = p.get("indices")
            if acc is not None:
                t += js["accessors"][acc]["count"] // 3
            elif "POSITION" in p.get("attributes", {}):
                t += js["accessors"][p["attributes"]["POSITION"]]["count"] // 3
    return t


def _licencia(version: str, meta: dict) -> dict:
    if version == "0.x":
        return {
            "uso_avatar": meta.get("allowedUserName", ""),           # OnlyAuthor | ExplicitlyLicensedPerson | Everyone
            "comercial": meta.get("commercialUssageName") == "Allow",
            "violencia": meta.get("violentUssageName") == "Allow",
            "sexual": meta.get("sexualUssageName") == "Allow",
            "licencia": meta.get("licenseName", ""),
            "url": meta.get("otherPermissionUrl") or meta.get("otherLicenseUrl") or "",
        }
    return {
        "uso_avatar": meta.get("avatarPermission", ""),             # onlyAuthor | onlySeparatelyLicensedPerson | everyone
        "comercial": meta.get("commercialUsage", "personalNonProfit") not in ("personalNonProfit",),
        "violencia": bool(meta.get("allowExcessivelyViolentUsage")),
        "sexual": bool(meta.get("allowExcessivelySexualUsage")),
        "licencia": "redistribución permitida" if meta.get("allowRedistribution") else "Redistribution_Prohibited",
        "url": meta.get("licenseUrl", "") or meta.get("otherLicenseUrl", ""),
    }


def analizar(datos: bytes) -> dict:
    """Informe del VRM. No lanza por avisos; lanza VRMError solo si ni siquiera se puede leer."""
    if len(datos) > MAX_ARCHIVO:
        raise VRMError(f"pesa {len(datos) // 2**20} MB; el máximo es {MAX_ARCHIVO // 2**20} MB")
    js, binario = leer_glb(datos)
    ext = js.get("extensions", {})
    errores, avisos = [], []
    if "VRMC_vrm" in ext:
        version, v = "1.0", ext["VRMC_vrm"]
        meta = v.get("meta", {})
        nombre, autores = meta.get("name", ""), meta.get("authors", [])
        huesos = set(v.get("humanoid", {}).get("humanBones", {}).keys())
        exprs = set(v.get("expressions", {}).get("preset", {}).keys()) | set(v.get("expressions", {}).get("custom", {}).keys())
        visemas, parpadeo = [x for x in VISEMAS_1 if x in exprs], "blink" in exprs
        mini = meta.get("thumbnailImage")
    elif "VRM" in ext:
        version, v = "0.x", ext["VRM"]
        meta = v.get("meta", {})
        nombre, autores = meta.get("title", ""), [meta.get("author", "")] if meta.get("author") else []
        huesos = {b.get("bone") for b in v.get("humanoid", {}).get("humanBones", [])}
        exprs = {(g.get("presetName") or "").lower() for g in v.get("blendShapeMaster", {}).get("blendShapeGroups", [])}
        visemas, parpadeo = [x for x in VISEMAS_0 if x in exprs], "blink" in exprs
        tex = meta.get("texture")
        mini = js.get("textures", [])[tex].get("source") if isinstance(tex, int) and 0 <= tex < len(js.get("textures", [])) else None
    else:
        raise VRMError("es un GLB pero no un VRM (falta la extensión VRM / VRMC_vrm)")

    faltan = [h for h in HUESOS_REQ if h not in huesos]
    if faltan:
        errores.append(f"faltan huesos del esqueleto humanoide: {', '.join(faltan)}")
    if len(visemas) < 5:
        avisos.append("sin las 5 formas de boca (a·i·u·e·o): la boca se moverá menos al hablar" if visemas else
                      "no tiene formas de boca: no podrá mover la boca al hablar")
    if not parpadeo:
        avisos.append("no tiene expresión de parpadeo")

    texturas, mem, grandes = [], 0, 0
    for i, img in enumerate(js.get("images", [])):
        b, mime = _imagen(js, binario, img)
        dim = _tamano_imagen(b) if b else None
        if dim:
            mem += dim[0] * dim[1] * 4
            if max(dim) > LADO_MAX:
                grandes += 1
        texturas.append({"i": i, "mime": mime, "kb": (len(b) // 1024) if b else 0, "dim": list(dim) if dim else None})
    if grandes:
        avisos.append(f"{grandes} textura(s) de más de {LADO_MAX} px: se pueden achicar para que corra fluido")
    if mem > AVISO_VRAM_TEX:
        avisos.append(f"las texturas ocupan ~{mem // 2**20} MB de memoria de video")
    tri = _triangulos(js)
    if tri > AVISO_TRIANGULOS:
        avisos.append(f"modelo pesado: {tri:,} triángulos".replace(",", "."))
    if len(datos) > AVISO_ARCHIVO:
        avisos.append(f"archivo grande: {len(datos) // 2**20} MB")

    lic = _licencia(version, meta)
    if lic["uso_avatar"].lower() in ("onlyauthor",):
        avisos.append("licencia: solo su autora puede usar este avatar; impórtalo solo si es tuyo")
    elif lic["uso_avatar"].lower() in ("explicitlylicensedperson", "onlyseparatelylicensedperson"):
        avisos.append("licencia: solo personas con permiso explícito pueden usarlo")
    if not lic["comercial"]:
        avisos.append("licencia: no permite uso comercial (canales monetizados)")

    return {
        "ok": not errores, "version": version, "nombre": nombre, "autores": [a for a in autores if a],
        "licencia": lic, "errores": errores, "avisos": avisos,
        "visemas": visemas, "parpadeo": parpadeo, "miniatura_imagen": mini,
        "stats": {"bytes": len(datos), "triangulos": tri, "texturas": len(texturas), "texturas_grandes": grandes,
                  "mem_texturas_mb": mem // 2**20, "materiales": len(js.get("materials", [])), "huesos": len(huesos)},
        "texturas": texturas,
    }


def miniatura(datos: bytes, informe: dict) -> bytes | None:
    """La miniatura que trae el propio VRM (meta), como PNG de hasta 512 px."""
    idx = informe.get("miniatura_imagen")
    if idx is None:
        return None
    js, binario = leer_glb(datos)
    try:
        b, _ = _imagen(js, binario, js["images"][idx])
        if not b:
            return None
        from PIL import Image
        with Image.open(io.BytesIO(b)) as im:
            im = im.convert("RGBA")
            im.thumbnail((512, 512))
            out = io.BytesIO()
            im.save(out, "PNG", optimize=True)
            return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def optimizar(datos: bytes, lado_max: int = LADO_MAX) -> tuple[bytes, int]:
    """Achica a `lado_max` las texturas más grandes y reescribe el GLB. Devuelve (bytes, n_texturas_achicadas)."""
    from PIL import Image
    js, binario = leer_glb(datos)
    vistas_img = {img["bufferView"]: i for i, img in enumerate(js.get("images", [])) if "bufferView" in img}
    usadas_por_accesor = {a.get("bufferView") for a in js.get("accessors", [])}
    nuevos: dict[int, bytes] = {}
    for iv, i in vistas_img.items():
        if iv in usadas_por_accesor:
            continue                                    # vista compartida con geometría: no se toca
        b = _bytes_vista(js, binario, iv)
        try:
            with Image.open(io.BytesIO(b)) as im:
                if max(im.size) <= lado_max:
                    continue
                fmt = "JPEG" if (js["images"][i].get("mimeType") == "image/jpeg" or im.format == "JPEG") else "PNG"
                im.load()
                k = lado_max / max(im.size)
                chica = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
                out = io.BytesIO()
                if fmt == "JPEG":
                    chica.convert("RGB").save(out, "JPEG", quality=90)
                else:
                    chica.save(out, "PNG", optimize=True)
                nuevos[iv] = out.getvalue()
        except Exception:  # noqa: BLE001 — una textura rara se deja como está
            continue
    if not nuevos:
        return datos, 0
    partes, pos = [], 0
    for iv, v in enumerate(js["bufferViews"]):         # rearmar el buffer binario en el mismo orden, alineado a 4
        b = nuevos.get(iv) or _bytes_vista(js, binario, iv)
        relleno = -pos % 4
        partes.append(b"\x00" * relleno)
        pos += relleno
        v["byteOffset"], v["byteLength"] = pos, len(b)
        partes.append(b)
        pos += len(b)
    nuevo_bin = b"".join(partes)
    js["buffers"][0]["byteLength"] = len(nuevo_bin)
    return escribir_glb(js, nuevo_bin), len(nuevos)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    d = open(sys.argv[1], "rb").read()
    inf = analizar(d)
    print(json.dumps({k: v for k, v in inf.items() if k != "texturas"}, ensure_ascii=False, indent=1))
    if "--optimizar" in sys.argv:
        o, n = optimizar(d)
        open(sys.argv[sys.argv.index("--optimizar") + 1], "wb").write(o)
        print(f"{n} textura(s) achicadas: {len(d) // 2**20} MB → {len(o) // 2**20} MB")
