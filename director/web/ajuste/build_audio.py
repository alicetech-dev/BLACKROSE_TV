"""Genera audio.wav (tonos de ajuste + voz en off) y guion.json para la carta de ajuste. Uso: ../../../.venv/bin/python build_audio.py"""
import asyncio, json, os, subprocess, edge_tts
HERE = os.path.dirname(os.path.abspath(__file__)); TMP = os.path.join(HERE, "_tmp"); os.makedirs(TMP, exist_ok=True)
VOZ, RATE = "es-MX-JorgeNeural", "-4%"
CUENTA = 40
AVISO = "Atención. Esto es una transmisión de ajuste de Blackrose TV. Verifica tu imagen y tu sonido. La señal comenzará en unos segundos."
OFF = [
 "Buenas tardes. Soy Claude, una inteligencia artificial creada por Anthropic, y hoy me toca encender la estación desde la sala de control.",
 "Bienvenidos a Blackrose TV, la televisión de la Corporación Blackrose. Transmitimos las veinticuatro horas, desde el año dos mil cuarenta y nueve hacia tu presente.",
 "La señal está conducida por Joy, la directora del canal, y por Kuroki, la productora y baterista. Dos nekos cibernéticas que investigan, conversan y presentan en vivo.",
 "Encontrarás tecnología, ciencia, videojuegos, programación, historias de hackers, misterios, noticias reales, sátira del futuro, y música libre en Radio Blackrose dos mil cuarenta y nueve. Cada noche, la Hora de Japón, con traducción.",
 "Puedes escribirnos en el chat de YouTube o de Twitch: te leemos al aire. Y si te gusta lo que ves, suscríbete y síguenos.",
 "Ajusta tu volumen. Comenzamos.",
]
async def tts(txt, ruta):
    await edge_tts.Communicate(txt, VOZ, rate=RATE).save(ruta)
def dur(f):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).decode())
async def main():
    textos = [AVISO] + OFF
    for i, t in enumerate(textos): await tts(t, f"{TMP}/v{i}.mp3")
    d = [dur(f"{TMP}/v{i}.mp3") for i in range(len(textos))]
    ini = [4.0]                                    # el aviso entra a los 4 s de la cuenta
    assert ini[0] + d[0] < CUENTA - 5, f"el aviso ({d[0]:.1f}s) no cabe en la cuenta"
    t = CUENTA + 1.4
    for i in range(1, len(textos)): ini.append(t); t += d[i] + 0.8
    total = t + 1.5
    entradas, filtros, mezcla = [], [], []
    def add(args, ms, vol):
        n = len(mezcla); entradas.extend(args)
        filtros.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},adelay={int(ms*1000)}|{int(ms*1000)}[a{n}]"); mezcla.append(f"[a{n}]")
    add(["-f", "lavfi", "-t", "2.5", "-i", "sine=frequency=1000:sample_rate=48000"], 0.5, 0.10)           # tono de ajuste
    for k, seg in enumerate((CUENTA - 3, CUENTA - 2, CUENTA - 1)):
        add(["-f", "lavfi", "-t", "0.18", "-i", "sine=frequency=880:sample_rate=48000"], seg, 0.22)         # pitidos de la cuenta
    add(["-f", "lavfi", "-t", "0.9", "-i", "sine=frequency=1000:sample_rate=48000"], CUENTA, 0.22)          # pitido largo: al aire
    for i in range(len(textos)): add(["-i", f"{TMP}/v{i}.mp3"], ini[i], 1.0)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(filtros) + ";" + "".join(mezcla) + f"amix=inputs={len(mezcla)}:normalize=0:duration=longest,apad=whole_dur={total:.2f}[o]",
           "-map", "[o]", "-ar", "48000", "-ac", "2", os.path.join(HERE, "audio.wav")]
    subprocess.check_call(cmd)
    g = {"cuenta": CUENTA, "total": round(total, 2), "voz": VOZ,
         "lineas": [{"t": round(ini[i], 2), "d": round(d[i], 2), "texto": textos[i]} for i in range(1, len(textos))]}
    json.dump(g, open(os.path.join(HERE, "guion.json"), "w"), ensure_ascii=False, indent=1)
    print("cuenta", CUENTA, "s · total", g["total"], "s · líneas", len(OFF)); [print(f"  {l['t']:6.1f}s +{l['d']:.1f}s  {l['texto'][:60]}") for l in g["lineas"]]
asyncio.run(main())
