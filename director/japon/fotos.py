#!/usr/bin/env python3
"""Fotos de Japón con LICENCIA LIBRE (Wikimedia Commons: CC0, dominio público, CC BY, CC BY-SA) + tus capturas de Fast Penguin.
Guarda en director/web/japon/img/ y deja japon/fotos.json con autor, licencia y fuente (el crédito sale en pantalla)."""
import glob, json, os, re, shutil, subprocess, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "..", "web", "japon", "img")
UA = {"User-Agent": "BlackRoseTV-japon/1.0"}
OK = re.compile(r"^(CC0|Public domain|PD|CC BY(-SA)? [0-9.]+|CC BY(-SA)?( [0-9.]+)?( \w+)?)$", re.I)
NO = re.compile(r"NC|ND|fair use|non-?free|GFDL only", re.I)
TEMAS = {   # id: (consulta, título ES, título JA)
    "fuji_sakura": ("Lake Kawaguchiko Sakura Mount Fuji", "El Monte Fuji y los cerezos en flor", "桜と富士山"),
    "fuji_amanecer": ("Sunrise with Mount Fuji", "Amanecer con el Monte Fuji", "富士山の日の出"),
    "tokio": ("Tokyo skyline night Shinjuku", "Tokio de noche", "東京の夜景"),
    "shibuya": ("Shibuya Crossing Tokyo", "El cruce de Shibuya", "渋谷スクランブル交差点"),
    "kabukicho": ("Kabukicho Shinjuku neon gate", "Kabukichō, Shinjuku", "歌舞伎町"),
    "fuji_speedway": ("Fuji Speedway", "Fuji Speedway", "富士スピードウェイ"),
    "suzuka": ("Suzuka Circuit", "Circuito de Suzuka", "鈴鹿サーキット"),
    "haruna": ("Mount Haruna Gunma", "Monte Haruna (Gunma)", "榛名山"),
    "tsushima": ("Tsushima Japan island coast", "Isla de Tsushima", "対馬"),
    "yotei": ("Mount Yotei Hokkaido", "Monte Yōtei, Hokkaido", "羊蹄山"),
    "himeji": ("Himeji Castle", "Castillo de Himeji", "姫路城"),
    "yokosuka": ("Yokosuka Japan harbor", "Yokosuka", "横須賀"),
    "torii": ("Itsukushima torii gate Miyajima", "Torii de Itsukushima", "厳島神社の鳥居"),
    "tokyo_tower": ("Tokyo Tower Minato", "Torre de Tokio", "東京タワー"),
}


def api(**p):
    p["format"] = "json"
    u = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(p)
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))


def buscar(q: str):
    r = api(action="query", generator="search", gsrsearch=q + " filetype:bitmap", gsrnamespace=6, gsrlimit=14, prop="imageinfo", iiprop="url|size|extmetadata|mime", iiurlwidth=1600)
    c = []
    for pg in (r.get("query", {}).get("pages", {}) or {}).values():
        ii = pg["imageinfo"][0]; m = ii.get("extmetadata", {})
        lic = m.get("LicenseShortName", {}).get("value", "")
        if not lic or NO.search(lic) or not (OK.match(lic.strip()) or lic.lower().startswith(("cc0", "public domain", "cc by"))):
            continue
        if ii["width"] < 1400 or ii["width"] < ii["height"] or not ii.get("thumburl") or "jpeg" not in ii.get("mime", "") and "png" not in ii.get("mime", ""):
            continue
        art = re.sub(r"<[^>]+>", "", m.get("Artist", {}).get("value", "")).strip()[:70] or "autor desconocido"
        c.append((pg["pageid"], pg["title"], lic.strip(), art, ii["thumburl"], ii["descriptionurl"], ii["width"]))
    c.sort(key=lambda x: -x[0] % 7)   # variedad
    return c


def main():
    lib = {}
    ruta = os.path.join(HERE, "fotos.json")
    try:
        lib = json.load(open(ruta, encoding="utf-8"))
    except (OSError, ValueError):
        lib = {}
    for fid, (q, es, ja) in TEMAS.items():
        if fid in lib and os.path.exists(os.path.join(IMG, lib[fid]["archivo"])):
            continue
        time.sleep(2.5)
        try:
            cand = buscar(q)
        except Exception as e:  # noqa: BLE001
            print("✗", fid, e); time.sleep(8); continue
        for (_, titulo, lic, art, url, desc, w) in cand[:4]:
            dest = os.path.join(IMG, fid + ".jpg")
            r = subprocess.run(["curl", "-sSL", "--fail", "-m", "90", "-A", UA["User-Agent"], "-o", dest, url], capture_output=True)
            if r.returncode == 0 and os.path.getsize(dest) > 60000:
                lib[fid] = {"archivo": fid + ".jpg", "es": es, "ja": ja, "titulo": titulo.replace("File:", ""), "autor": art, "licencia": lic, "fuente": desc,
                            "credito": f"Foto: {art} · {lic} · Wikimedia Commons"}
                print("✓", fid, lic, art); break
        else:
            print("✗ sin foto utilizable:", fid)
    # tus capturas de Fast Penguin (propias: sin licencia que citar)
    mias = sorted(glob.glob(os.path.expanduser("~/.local/share/Steam/userdata/*/760/remote/2590150/screenshots/*.jpg"))) + [os.path.expanduser("~/fotos_fast_pengui/con_ibrand.png")]
    for i, f in enumerate(mias):
        if not os.path.exists(f):
            continue
        fid = f"fp_{i+1}"
        dest = os.path.join(IMG, fid + ".jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", f, "-vf", "scale=1600:-2", "-q:v", "3", dest])
        lib[fid] = {"archivo": fid + ".jpg", "es": "Captura de Fast Penguin", "ja": "Fast Penguin のスクリーンショット", "titulo": os.path.basename(f), "autor": "Blackrose", "licencia": "propia", "fuente": "", "credito": "Captura: Blackrose · Fast Penguin"}
        print("✓", fid, "(tuya)")
    json.dump(lib, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(lib), "fotos")


main()
