#!/usr/bin/env python3
"""BIBLIOTECA del canal nocturno de BlackRose TV: SOLO material con licencia que permite emitirlo.

  · Blender Foundation (Sintel, Elephants Dream, Tears of Steel, Cosmos Laundromat, Caminandes, Big Buck Bunny, Spring): CC BY → se muestra el crédito en pantalla.
  · NASA (images.nasa.gov): contenido de la NASA, sin copyright (se cita la fuente; se saltan los que declaran otro autor).
  · Kevin MacLeod (incompetech.com): música CC BY 4.0 → crédito en pantalla.
  · Prelinger Archives (archive.org): solo ítems con licencia «dominio público» declarada.
Cada archivo queda en web/tv/media/ y en tv/biblioteca.json con licencia, autor, fuente y texto de atribución.
Uso:  .venv/bin/python director/tv/bajar.py [musica|blender|nasa|prelinger|todo]      (idempotente: lo ya bajado se salta)
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "..", "web", "tv", "media")
LIB = os.path.join(HERE, "biblioteca.json")
UA = {"User-Agent": "BlackRoseTV-biblioteca/1.0"}
os.makedirs(os.path.join(MEDIA, "v"), exist_ok=True)
os.makedirs(os.path.join(MEDIA, "m"), exist_ok=True)


def cargar() -> dict:
    try:
        return json.load(open(LIB, encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": []}


def guardar(d: dict) -> None:
    json.dump(d, open(LIB + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(LIB + ".tmp", LIB)


def get(url: str, t: int = 30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t)


def jget(url: str):
    return json.load(get(url))


def bajar(url: str, dest: str) -> bool:
    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        return True
    r = subprocess.run(["curl", "-sSL", "--fail", "--retry", "3", "-m", "1500", "-A", UA["User-Agent"], "-o", dest + ".part", url], capture_output=True, text=True)
    if r.returncode != 0:
        print("  ✗ descarga falló:", r.stderr.strip()[:120], flush=True)
        try:
            os.remove(dest + ".part")
        except OSError:
            pass
        return False
    os.replace(dest + ".part", dest)
    return True


def sonda(path: str) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", path], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
    except ValueError:
        return {}
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"dur": float(j.get("format", {}).get("duration") or 0), "vc": v.get("codec_name"), "ac": a.get("codec_name"), "w": v.get("width") or 0, "h": v.get("height") or 0}


def a_mp4(src: str, dest: str) -> bool:
    """Deja un mp4 H.264/AAC ≤720p (el navegador de OBS lo reproduce seguro). Copia sin recodificar si ya lo es."""
    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        return True
    s = sonda(src)
    if not s.get("dur"):
        return False
    if s["vc"] == "h264" and s["ac"] in ("aac", None) and s["h"] <= 720:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-c", "copy", "-movflags", "+faststart", dest]
    else:
        cmd = ["nice", "-n", "19", "ffmpeg", "-y", "-v", "error", "-i", src, "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", dest]
    ok = subprocess.run(cmd).returncode == 0 and os.path.exists(dest)
    return ok


def alta(item: dict) -> None:
    with open(LIB + ".lock", "w") as lk:          # las descargas corren en paralelo: un candado para no pisar el json
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = cargar()
        d["items"] = [i for i in d["items"] if i["id"] != item["id"]] + [item]
        guardar(d)
    print(f"  ✓ {item['id']} · {item['dur']/60:.1f} min · {item['licencia']}", flush=True)


# ───────────────────────────── música (Kevin MacLeod, CC BY 4.0) ─────────────────────────────
MUSICA = {   # título → (humor, para qué bloques)
    "Wallpaper": ("suave", ["noticias", "madrugada"]), "Sneaky Snitch": ("misterio-juguetón", ["conspira", "hackers"]),
    "Cyborg Ninja": ("cyberpunk", ["musica", "hackers", "tecnooculta"]), "Machinations": ("tensión", ["hackers", "conspira"]),
    "Mechanolith": ("industrial", ["tecnooculta", "musica"]), "Digital Lemonade": ("electro", ["musica", "videojuegos"]),
    "Industrial Revolution": ("industrial", ["tecnooculta", "noticias"]), "Rocket Power": ("energía", ["deportes", "musica"]),
    "Space Jazz": ("espacial", ["alien", "musica"]), "Fluidscape": ("ambiental", ["alien", "madrugada"]),
    "Dark Fog": ("oscuro", ["conspira", "alien"]), "Darkest Child": ("oscuro", ["conspira", "alien"]),
    "Funkorama": ("funk", ["musica", "deportes"]), "Voxel Revolution": ("8bit", ["videojuegos", "musica"]),
    "Hidden Agenda": ("misterio", ["conspira", "hackers"]), "Robobozo": ("robot", ["tecnooculta", "videojuegos"]),
    "Take a Chance": ("pop-electro", ["musica", "deportes"]), "Pixelland": ("8bit", ["videojuegos"]),
    "8bit Dungeon Boss": ("8bit", ["videojuegos", "musica"]), "Newer Wave": ("synthwave", ["musica", "noticias"]),
    "Netherworld Shanty": ("oscuro", ["alien", "conspira"]), "Danger Storm": ("acción", ["deportes", "hackers"]),
    "Ghost Story": ("misterio", ["alien", "conspira"]), "Lightless Dawn": ("ambiental", ["alien", "madrugada"]),
    "Comfortable Mystery 4": ("misterio", ["conspira", "alien"]), "Impact Moderato": ("épico", ["noticias", "deportes"]),
}


def musica() -> None:
    print("== música Kevin MacLeod", flush=True)
    for t, (humor, bl) in MUSICA.items():
        idn = "m_" + re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")
        dest = os.path.join(MEDIA, "m", idn + ".mp3")
        url = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/" + urllib.parse.quote(t) + ".mp3"
        if not bajar(url, dest):
            continue
        s = sonda(dest)
        if s.get("dur", 0) < 30:
            continue
        alta({"id": idn, "tipo": "musica", "titulo": t, "autor": "Kevin MacLeod", "licencia": "CC BY 4.0", "fuente": "https://incompetech.com/music/royalty-free/",
              "atribucion": f"Música: «{t}» — Kevin MacLeod (incompetech.com) · Licencia CC BY 4.0", "archivo": f"m/{idn}.mp3", "dur": s["dur"], "humor": humor, "bloques": bl})


# ───────────────────────────── Blender (CC BY) vía archive.org ─────────────────────────────
BLENDER = [  # id archive.org, título, año, licencia, bloques, resumen corto
    ("Sintel", "Sintel", 2010, "CC BY 3.0", ["musica", "videojuegos", "madrugada"], "Una joven y un dragón bebé; fantasía animada hecha 100 % con software libre."),
    ("ElephantsDream", "Elephants Dream", 2006, "CC BY 2.5", ["tecnooculta", "videojuegos", "hackers"], "La primera película abierta de Blender: dos hombres dentro de una máquina enorme y extraña."),
    ("CosmosLaundromatFirstCycle", "Cosmos Laundromat", 2015, "CC BY 4.0", ["alien", "conspira", "madrugada"], "Una oveja deprimida y un vendedor de vidas: animación surreal de Blender."),
    ("CaminandesLlamigos", "Caminandes: Llamigos", 2016, "CC BY 3.0", ["deportes", "videojuegos"], "Una llama y un armadillo; humor físico en 2 minutos."),
    ("BigBuckBunny1280x720Stereo", "Big Buck Bunny", 2008, "CC BY 3.0", ["deportes", "madrugada"], "El conejo gigante contra tres roedores abusivos: el clásico de Blender."),
    ("spring_blenderopenmovie", "Spring", 2019, "CC BY 4.0", ["alien", "madrugada", "musica"], "Una pastora y su perro frente a espíritus antiguos: la más bonita de Blender."),
]


def blender() -> None:
    print("== Blender / archive.org", flush=True)
    for ident, titulo, anio, lic, bl, resumen in BLENDER:
        idn = "v_" + re.sub(r"[^a-z0-9]+", "_", titulo.lower()).strip("_")
        dest = os.path.join(MEDIA, "v", idn + ".mp4")
        if os.path.exists(dest):
            continue
        try:
            meta = jget(f"https://archive.org/metadata/{ident}")
        except Exception as e:  # noqa: BLE001
            print("  ✗ metadata", ident, e)
            continue
        cand = [f for f in meta.get("files", []) if re.search(r"\.(mp4|m4v|mov|ogv|webm|mkv)$", f["name"], re.I) and 20e6 < int(f.get("size") or 0) < 900e6]
        if not cand:
            print("  ✗ sin archivo utilizable en", ident)
            continue
        # el más liviano que no sea miniatura: preferimos mp4 de tamaño medio
        cand.sort(key=lambda f: (0 if f["name"].lower().endswith(".mp4") else 1, abs(int(f["size"]) - 150e6)))
        f = cand[0]
        print(f"  ↓ {titulo}: {f['name']} ({int(f['size'])/1e6:.0f} MB)", flush=True)
        crudo = os.path.join(MEDIA, "v", "_" + re.sub(r"[^A-Za-z0-9.]+", "_", f["name"]))
        if not bajar(f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}", crudo):
            continue
        if not a_mp4(crudo, dest):
            print("  ✗ conversión falló")
            continue
        os.remove(crudo)
        s = sonda(dest)
        alta({"id": idn, "tipo": "video", "titulo": titulo, "autor": "Blender Foundation", "licencia": lic, "fuente": f"https://archive.org/details/{ident}",
              "atribucion": f"«{titulo}» ({anio}) © Blender Foundation · www.blender.org · {lic}", "archivo": f"v/{idn}.mp4", "dur": s["dur"], "bloques": bl, "resumen": resumen, "categoria": "corto animado"})


# ───────────────────────────── NASA ─────────────────────────────
NASA = [  # consulta, bloques, categoría
    ("search for life exoplanet", ["alien"], "ciencia"), ("Mars Perseverance rover", ["alien", "tecnooculta"], "ciencia"),
    ("technosignatures SETI", ["alien"], "ciencia"), ("Europa Clipper icy moon ocean", ["alien"], "ciencia"),
    ("James Webb telescope exoplanet", ["alien", "noticias"], "ciencia"), ("Voyager golden record", ["alien", "tecnooculta"], "historia"),
    ("Apollo guidance computer", ["tecnooculta", "hackers"], "historia"), ("X-15 rocket plane", ["tecnooculta"], "historia"),
    ("Hubble servicing mission", ["tecnooculta", "madrugada"], "historia"), ("Ingenuity Mars helicopter", ["tecnooculta", "videojuegos"], "ciencia"),
    ("Earth from space ISS timelapse", ["madrugada", "musica"], "imágenes"), ("aurora from the International Space Station", ["madrugada", "musica"], "imágenes"),
    ("solar storm Sun Solar Dynamics Observatory", ["noticias", "madrugada"], "ciencia"), ("Artemis moon mission", ["noticias", "deportes"], "ciencia"),
    ("Apollo 11 moon landing documentary", ["conspira", "tecnooculta", "deportes"], "historia"), ("space race history Sputnik", ["conspira", "tecnooculta"], "historia"),
    ("New Horizons Pluto flyby", ["alien", "madrugada"], "ciencia"), ("Parker Solar Probe", ["noticias", "tecnooculta"], "ciencia"),
    ("International Space Station tour", ["videojuegos", "deportes", "noticias"], "imágenes"), ("Hubble deep field universe", ["alien", "madrugada", "musica"], "imágenes"),
    ("NASA supercomputer simulation", ["hackers", "videojuegos", "tecnooculta"], "tecnología"), ("robotics rover technology NASA", ["hackers", "videojuegos", "tecnooculta"], "tecnología"),
    ("astronaut training athletes fitness", ["deportes"], "ciencia"), ("NASA drone aircraft X-57 electric", ["deportes", "tecnooculta", "hackers"], "tecnología"),
    ("cybersecurity NASA", ["hackers"], "tecnología"), ("asteroid planetary defense DART", ["alien", "noticias", "conspira"], "ciencia"),
    ("Mars sample return meteorite life", ["alien", "conspira"], "ciencia"), ("black hole visualization", ["alien", "musica", "madrugada"], "imágenes"),
]


def nasa() -> None:
    print("== NASA", flush=True)
    for q, bl, cat in NASA:
        try:
            res = jget("https://images-api.nasa.gov/search?" + urllib.parse.urlencode({"q": q, "media_type": "video"}))["collection"]["items"]
        except Exception as e:  # noqa: BLE001
            print("  ✗ búsqueda", q, e)
            continue
        hecho = 0
        for it in res[:25]:
            if hecho >= 4:
                break
            d = it["data"][0]
            nid = d["nasa_id"]
            idn = "v_nasa_" + re.sub(r"[^a-z0-9]+", "_", nid.lower())[:40]
            if any(i["id"] == idn for i in cargar()["items"]):
                hecho += 1
                continue
            if d.get("secondary_creator") or "copyright" in json.dumps(d).lower():   # otro autor → fuera
                continue
            try:
                urls = jget(it["href"])
            except Exception:  # noqa: BLE001
                continue
            mp4 = [u for u in urls if u.lower().endswith(".mp4")]
            pref = next((u for u in mp4 if "~medium" in u), None) or next((u for u in mp4 if "~preview" not in u and "~small" not in u and "~mobile" not in u), None) or next(iter(mp4), None)
            if not pref:
                continue
            crudo = os.path.join(MEDIA, "v", "_" + idn + ".mp4")
            dest = os.path.join(MEDIA, "v", idn + ".mp4")
            if not bajar(pref.replace("http://", "https://"), crudo):
                continue
            s = sonda(crudo)
            if not (60 <= s.get("dur", 0) <= 1500):
                os.remove(crudo)
                continue
            if not a_mp4(crudo, dest):
                continue
            os.remove(crudo)
            titulo = d["title"].strip()
            alta({"id": idn, "tipo": "video", "titulo": titulo, "autor": "NASA", "licencia": "NASA (sin copyright)", "fuente": f"https://images.nasa.gov/details/{nid}",
                  "atribucion": f"«{titulo}» — NASA · images.nasa.gov", "archivo": f"v/{idn}.mp4", "dur": s["dur"], "bloques": bl, "resumen": (d.get("description") or "")[:400], "categoria": cat})
            hecho += 1


# ───────────────────────────── Prelinger (dominio público declarado) ─────────────────────────────
PRELINGER = [("subject:(sports) AND collection:prelinger", ["deportes"], "archivo histórico"), ("subject:(computers) AND collection:prelinger", ["hackers", "tecnooculta", "videojuegos"], "archivo histórico"),
             ("subject:(atomic) AND collection:prelinger", ["conspira", "tecnooculta"], "archivo histórico")]


def prelinger() -> None:
    print("== Prelinger (dominio público)", flush=True)
    for consulta, bl, cat in PRELINGER:
        u = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode({"q": consulta + " AND mediatype:movies", "fl[]": ["identifier", "title", "licenseurl", "runtime"], "rows": 30, "sort[]": "downloads desc", "output": "json"}, doseq=True)
        try:
            docs = jget(u)["response"]["docs"]
        except Exception as e:  # noqa: BLE001
            print("  ✗", consulta, e)
            continue
        hecho = 0
        for d in docs:
            if hecho >= 2:
                break
            lic = d.get("licenseurl", "")
            if "publicdomain" not in lic and "/zero/" not in lic:
                continue
            ident = d["identifier"]
            idn = "v_pre_" + re.sub(r"[^a-z0-9]+", "_", ident.lower())[:40]
            dest = os.path.join(MEDIA, "v", idn + ".mp4")
            if os.path.exists(dest):
                hecho += 1
                continue
            try:
                meta = jget(f"https://archive.org/metadata/{ident}")
            except Exception:  # noqa: BLE001
                continue
            cand = [f for f in meta.get("files", []) if re.search(r"\.(mp4|m4v|ogv|mpeg|mpg)$", f["name"], re.I) and 15e6 < int(f.get("size") or 0) < 400e6 and "thumb" not in f["name"].lower()]
            if not cand:
                continue
            cand.sort(key=lambda f: (0 if f["name"].lower().endswith(".mp4") else 1, int(f["size"])))
            f = cand[0]
            crudo = os.path.join(MEDIA, "v", "_" + idn + os.path.splitext(f["name"])[1])
            if not bajar(f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}", crudo):
                continue
            s = sonda(crudo)
            if not (120 <= s.get("dur", 0) <= 1100) or not a_mp4(crudo, dest):
                try:
                    os.remove(crudo)
                except OSError:
                    pass
                continue
            os.remove(crudo)
            titulo = d.get("title", ident)
            alta({"id": idn, "tipo": "video", "titulo": titulo, "autor": "Prelinger Archives", "licencia": "dominio público (declarado en archive.org)", "fuente": f"https://archive.org/details/{ident}",
                  "atribucion": f"«{titulo}» — Prelinger Archives / Internet Archive · dominio público", "archivo": f"v/{idn}.mp4", "dur": s["dur"], "bloques": bl, "resumen": "", "categoria": cat})
            hecho += 1


if __name__ == "__main__":
    que = sys.argv[1] if len(sys.argv) > 1 else "todo"
    for nombre, fn in (("musica", musica), ("blender", blender), ("nasa", nasa), ("prelinger", prelinger)):
        if que in ("todo", nombre):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                print("✗", nombre, repr(e), flush=True)
    d = cargar()
    print(f"\nBiblioteca: {len(d['items'])} ítems · {sum(i['dur'] for i in d['items'])/3600:.1f} h", flush=True)
