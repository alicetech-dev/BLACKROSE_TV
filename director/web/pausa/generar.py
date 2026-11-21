#!/usr/bin/env python3
"""Genera el material de la PAUSA COMERCIAL de BlackRose TV (estilo MTV cyberpunk / futuro retro): locuciones con varias voces
(edge-tts, gratis, sin tokens), 3 camas musicales sintetizadas y spots.json.

  cd ~/joy_vmc && .venv/bin/python director/web/pausa/generar.py            # todo
  cd ~/joy_vmc && .venv/bin/python director/web/pausa/generar.py voz        # solo las voces (tras editar un texto)
  cd ~/joy_vmc && .venv/bin/python director/web/pausa/generar.py musica     # solo las camas

Agregar un spot: añadí una línea a SPOTS y volvé a generar (la página los mezcla sola, sin repetir hasta agotar la bolsa).
  fmt    = ident (sting corto) | vj (texto cinético, voz de VJ) | ad (comercial parodia) | quiz (pregunta al chat) | std (programa / dato)
  voz    = doc (narrador de documental) | vj | ad | chica
  visual = marca | chip | mando | neurona | globo | penguin | dato | holo | vhs | memphis | sunburst
"""
import asyncio
import json
import os
import subprocess
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(AQUI, "media")
VOCES = {   # voz, velocidad, tono
    "doc":   ("es-MX-JorgeNeural", "-6%", "-8Hz"),     # narrador de documental
    "vj":    ("es-MX-DaliaNeural", "+8%", "+4Hz"),      # VJ juvenil
    "ad":    ("es-US-AlonsoNeural", "+14%", "+2Hz"),    # locutor de comercial
    "chica": ("es-US-PalomaNeural", "+4%", "+0Hz"),     # stings
}

R, C, Y, V, G, O = "#ff2fd6", "#00e5ff", "#ffe45e", "#b46bff", "#3dff9a", "#ff8f6b"


def S(id, fmt, visual, voz, tag, titulo, sub, color, texto, **x):
    return dict(id=id, fmt=fmt, visual=visual, voz=voz, tag=tag, titulo=titulo, sub=sub, color=color, texto=texto, **x)


SPOTS = [
    # ── stings (2-3 s): el logo en 6 animaciones distintas, la página elige una al azar ──
    S("id_blackrose", "ident", "vhs", "chica", "", "BLACKROSE TV", "señal pirata", R, "BlackRose TV."),
    S("id_pirata", "ident", "memphis", "chica", "", "BLACKROSE TV", "sin filtro", C, "Señal pirata."),
    S("id_mansion", "ident", "holo", "chica", "", "BLACKROSE TV", "directo desde la mansión", V, "Directo desde la Mansión."),
    S("id_actitud", "ident", "vhs", "vj", "", "BLACKROSE TV", "tecnología con actitud", Y, "Tecnología con actitud."),
    S("id_wifi", "ident", "memphis", "vj", "", "BLACKROSE TV", "más rápido que tu wifi", G, "Más rápido que tu wifi."),
    S("id_neon", "ident", "holo", "chica", "", "BLACKROSE TV", "24/7 en neón", O, "BlackRose TV. Veinticuatro siete, en neón."),

    # ── VJ: texto cinético, tono juvenil ──
    S("vj_tu", "vj", "vj", "vj", "VJ BLACKROSE", "OYE TÚ SÍ TÚ", "no cambies de canal", R,
      "Oye tú. Sí, tú. Estás en BlackRose TV, el único canal donde la tecnología no da sueño. Sube el volumen."),
    S("vj_cafe", "vj", "vj", "vj", "VJ BLACKROSE", "ESTÍRATE TOMA AGUA RECARGA", "la pausa también es tuya", C,
      "Aprovecha la pausa: estírate, toma agua y recarga el café. Nosotros seguimos aquí, brillando en neón."),
    S("vj_vecinos", "vj", "vj", "vj", "VJ BLACKROSE", "MÁS VOLUMEN", "los vecinos lo agradecerán", Y,
      "Si tus vecinos no se quejan, no estás viendo suficiente BlackRose TV."),
    S("vj_chat", "vj", "vj", "vj", "VJ BLACKROSE", "TU CHAT SIGUE VIVO", "twitch · discord", G,
      "Esto es una pausa, pero tu chat sigue vivo. Escribe lo que quieras en Twitch o en Discord: Blackrose lo lee cuando vuelva."),
    S("vj_sigue", "vj", "vj", "vj", "VJ BLACKROSE", "SÍGUENOS", "barbieblackrose · twitch · youtube", V,
      "Síguenos en Twitch y en YouTube: barbieblackrose. Dale al botón, activa la campanita y arma la fiesta."),
    S("vj_lo_bueno", "vj", "vj", "vj", "VJ BLACKROSE", "LO BUENO VIENE AHORA", "hackeos · gadgets · juegos", O,
      "No te vayas, que lo bueno viene ahora: hackeos, gadgets, videojuegos y cero aburrimiento."),

    # ── comerciales parodia (productos ficticios; el aviso va en pantalla) ──
    S("ad_noodles", "ad", "sunburst", "ad", "COMERCIAL (FICTICIO)", "NEON NOODLES", "los fideos de los hackers", Y,
      "¡Neon Noodles! Los fideos instantáneos de los hackers. Listos en tres minutos, con el sabor de una madrugada de código. Neon Noodles: compílalos, cómelos.",
      precio="¡SOLO 19,99 CRÉDITOS!"),
    S("ad_hoverboard", "ad", "sunburst", "ad", "COMERCIAL (FICTICIO)", "HOVERBOARD 2015", "flota, no camines", C,
      "¿Cansado de caminar? Presentamos el Hoverboard Retro Dos Mil Quince. Flota, desliza y llega tarde con estilo. Algunas leyes de la física no incluidas.",
      precio="¡SIN RUEDAS!"),
    S("ad_chicle", "ad", "sunburst", "ad", "COMERCIAL (FICTICIO)", "CIBERCHICLE", "se actualiza solo", G,
      "Ciberchicle: el chicle que se actualiza solo. Menta en la versión uno, frutilla en la versión dos. Reinicia tu aliento.",
      precio="V2.0 GRATIS"),
    S("ad_vhs", "ad", "sunburst", "ad", "COMERCIAL (FICTICIO)", "VHS A LA NUBE", "tus recuerdos, sin rebobinar", R,
      "Digitalizamos tus VHS en la nube. Tus recuerdos de los noventa, ahora sin cinta que rebobinar. Sé amable: ya no rebobines.",
      precio="¡SIN RUIDO!"),
    S("ad_energy", "ad", "sunburst", "ad", "COMERCIAL (FICTICIO)", "BLACK ROSE ENERGY", "sabor a ping de 1 ms", V,
      "Black Rose Energy. Sabor a ping de un milisegundo. Cuidado: puede causar speedruns involuntarios.",
      precio="¡LATA XL!"),
    S("ad_internet", "ad", "sunburst", "ad", "COMERCIAL (FICTICIO)", "INTERNET PREMIUM PLUS", "paciencia incluida", O,
      "Internet Premium Plus: la mitad de velocidad por el doble de precio. Porque la paciencia también es una virtud.",
      precio="¡LETRA CHICA!"),

    # ── datos curiosos / futuro retro (narrador de documental) ──
    S("dato_bttf", "std", "holo", "doc", "RETRO-FUTURO", "EL FUTURO QUE IMAGINARON", "volver al futuro II · año 2015", Y,
      "En mil novecientos ochenta y nueve, Volver al Futuro Dos imaginó el dos mil quince con hoverboards, autos voladores y videollamadas. "
      "Las videollamadas llegaron. Los hoverboards, todavía los estamos esperando."),
    S("dato_arpanet", "std", "dato", "doc", "DATO TECH", "SABÍAS QUE", "el primer mensaje de internet fue «LO»", Y,
      "¿Sabías que? El veintinueve de octubre de mil novecientos sesenta y nueve se envió el primer mensaje por ARPANET, el antepasado de internet. "
      "Debía decir «login», pero el sistema se cayó tras las dos primeras letras. El primer mensaje de internet fue: «lo»."),
    S("dato_cafetera", "std", "dato", "doc", "DATO TECH", "SABÍAS QUE", "la primera webcam vigilaba una cafetera", C,
      "¿Sabías que? Una de las primeras cámaras web del mundo, en la Universidad de Cambridge, a principios de los noventa, "
      "se instaló para vigilar una cafetera, y así saber si quedaba café sin subir las escaleras."),
    S("dato_linux", "std", "dato", "doc", "DATO TECH", "SABÍAS QUE", "Linux empezó como «solo un hobby»", G,
      "¿Sabías que? En mil novecientos noventa y uno, un estudiante finlandés llamado Linus Torvalds anunció un sistema operativo: «solo un hobby, nada grande ni profesional». "
      "Hoy esa idea, Linux, mueve servidores, teléfonos y supercomputadoras."),
    S("dato_bug", "std", "dato", "doc", "DATO TECH", "SABÍAS QUE", "el «primer bug» fue una polilla", O,
      "¿Sabías que? En mil novecientos cuarenta y siete, operadores del Harvard Mark II encontraron una polilla atrapada en un relé y la pegaron en la bitácora: "
      "«primer caso real de bug encontrado». La palabra ya se usaba antes, pero la anécdota se volvió leyenda."),
    S("dato_mouse", "std", "chip", "doc", "DATO TECH", "SABÍAS QUE", "el primer mouse era de madera", C,
      "¿Sabías que? El primer prototipo de mouse de computadora, creado por Douglas Engelbart en los años sesenta, tenía una carcasa de madera."),
    S("dato_movil", "std", "holo", "doc", "DATO TECH", "SABÍAS QUE", "la primera llamada móvil fue en 1973", R,
      "¿Sabías que? La primera llamada desde un teléfono móvil se hizo en mil novecientos setenta y tres, con un aparato que pesaba más de un kilo."),
    S("dato_email", "std", "dato", "doc", "DATO TECH", "SABÍAS QUE", "la arroba nació con el primer email", V,
      "¿Sabías que? Ray Tomlinson envió el primer correo electrónico en red en mil novecientos setenta y uno, y fue quien eligió la arroba para separar el usuario del equipo."),
    S("dato_com", "std", "chip", "doc", "DATO TECH", "SABÍAS QUE", "el primer .com fue symbolics.com", Y,
      "¿Sabías que? El primer dominio punto com registrado fue symbolics punto com, en mil novecientos ochenta y cinco."),
    S("dato_tennis", "std", "mando", "doc", "DATO GAMER", "SABÍAS QUE", "un videojuego de 1958 usaba un osciloscopio", R,
      "¿Sabías que? Tennis for Two, de mil novecientos cincuenta y ocho, es uno de los primeros videojuegos de la historia y se jugaba en la pantalla de un osciloscopio."),

    # ── programas de BlackRose TV ──
    S("tecnologia", "std", "chip", "doc", "EN BLACKROSE TV", "TECNOLOGÍA", "hardware · software · Linux · ciencia", C,
      "Tecnología. Hardware, software, Linux y ciencia. Cada día, lo que de verdad importa, sin humo ni hype. Solo en BlackRose TV."),
    S("gamer", "std", "mando", "doc", "EN BLACKROSE TV", "NOTICIAS GAMER", "lanzamientos · industria · esports · indie", R,
      "Noticias gamer. Lanzamientos, industria, esports y juegos indie. Opiniones fuertes, cero fanboys. Solo en BlackRose TV."),
    S("ia", "std", "neurona", "doc", "EN BLACKROSE TV", "INTELIGENCIA ARTIFICIAL", "modelos · empresas · regulación · impacto", V,
      "Inteligencia artificial. Modelos, empresas, regulación e impacto. Una inteligencia artificial hablando de inteligencia artificial. Solo en BlackRose TV."),
    S("internacional", "std", "globo", "doc", "EN BLACKROSE TV", "CONTINGENCIA INTERNACIONAL", "geopolítica · economía · conflictos · cumbres", "#ff3b3b",
      "Contingencia internacional. Geopolítica, economía y conflictos, explicados con calma y desde varios lados. Solo en BlackRose TV."),
    S("fastpenguin", "std", "penguin", "vj", "EN VIVO CON BLACKROSE", "FAAAST PENGUIN", "hasta 40 jugadores · pisa, salta y acelera", "#6ee7ff",
      "Faaast Penguin. Hasta cuarenta jugadores, una pista, y pisar a tus rivales es la regla. Juega con Blackrose: el código de party aparece en pantalla."),

    # ── preguntas al chat ──
    S("q_primer", "quiz", "holo", "vj", "PREGUNTA AL CHAT", "¿CUÁL FUE EL PRIMER VIDEOJUEGO QUE JUGASTE?", "respóndelo en twitch o discord", C,
      "Pregunta para el chat: ¿cuál fue el primer videojuego que jugaste? Cuéntalo en Twitch o en Discord."),
    S("q_so", "quiz", "holo", "vj", "PREGUNTA AL CHAT", "LINUX, WINDOWS O MAC", "defiende tu bando", G,
      "Pregunta para el chat: ¿Linux, Windows o Mac? Defiende tu bando, pero con respeto."),
    S("q_carreras", "quiz", "holo", "vj", "PREGUNTA AL CHAT", "¿EL MEJOR JUEGO DE CARRERAS DE LA HISTORIA?", "sin peleas, ¡bueno, con pocas!", Y,
      "Pregunta para el chat: ¿cuál es el mejor juego de carreras de la historia? Escríbelo ahora."),
    S("q_hover", "quiz", "holo", "vj", "PREGUNTA AL CHAT", "SI TUVIERAS UN HOVERBOARD, ¿A DÓNDE IRÍAS?", "el futuro es hoy", R,
      "Pregunta para el chat: si tuvieras un hoverboard hoy, ¿a dónde irías primero?"),

    # ── cortes random estilo MTV: chistes y datos de tecnología / IA (texto cinético) ──
    S("c_wifi", "vj", "vj", "vj", "CORTE RANDOM", "TU WIFI", "cinco barras, cargando como en 1998", R, "Tu wifi: cinco barras. Tu página: cargando desde mil novecientos noventa y ocho."),
    S("c_ctrlz", "vj", "vj", "vj", "CORTE RANDOM", "CTRL Z", "la única máquina del tiempo que funciona", C, "Control zeta: la única máquina del tiempo que sí funciona."),
    S("c_ia_mano", "vj", "vj", "vj", "CORTE RANDOM", "LA IA DIBUJA UNA MANO", "siete dedos y mucha confianza", Y, "Le pedí a una inteligencia artificial que dibujara una mano. Me dio siete dedos y mucha confianza."),
    S("c_reinicia", "vj", "vj", "vj", "CORTE RANDOM", "¿LO REINICIASTE?", "resuelve el 90% de los problemas", G, "¿Probaste apagarlo y volverlo a encender? Resuelve el noventa por ciento de los problemas. El otro diez es magia negra."),
    S("c_pass", "vj", "vj", "vj", "CORTE RANDOM", "QWERTY ESTORNUDÓ", "salud · cámbiala ya", V, "Tu contraseña qwerty acaba de estornudar. Salud. Cámbiala."),
    S("c_update", "vj", "vj", "vj", "CORTE RANDOM", "ACTUALIZANDO 8 MINUTOS", "ya van tres horas", O, "Una actualización de ocho minutos. Ya van tres horas. El progreso no es una línea recta."),
    S("c_bateria", "vj", "vj", "vj", "CORTE RANDOM", "20% DE BATERÍA", "tu cargador no está donde lo dejaste", R, "Veinte por ciento de batería: la señal universal de que el cargador no está donde lo dejaste."),
    S("c_nube", "vj", "vj", "vj", "CORTE RANDOM", "LA NUBE NO ES MAGIA", "son computadoras de otra persona", C, "La nube no es magia: son computadoras de otra persona, con aire acondicionado."),
    S("c_gatos", "vj", "vj", "vj", "CORTE RANDOM", "INTERNET: MISIÓN CUMPLIDA", "ahora sirve para ver gatos", Y, "Internet nació para compartir conocimiento científico. Hoy sirve sobre todo para ver gatos. Misión cumplida."),
    S("c_bug", "vj", "vj", "vj", "CORTE RANDOM", "NO ES UN BUG", "es una característica no documentada", G, "No es un bug, es una característica no documentada."),
    S("c_oscuro", "vj", "vj", "vj", "CORTE RANDOM", "MODO OSCURO", "porque tus ojos a las 3 AM merecen respeto", V, "Modo oscuro: porque tus ojos a las tres de la mañana también merecen respeto."),
    S("c_ia_poema", "vj", "vj", "vj", "CORTE RANDOM", "DATO RANDOM IA", "un poema sí, el ruido de tu cafetera no", O, "Dato random: una inteligencia artificial te escribe un poema sobre tu cafetera, pero todavía no sabe por qué la tuya hace ese ruido."),

    # ── cierre ──
    S("vuelve", "vj", "vj", "vj", "PAUSA COMERCIAL", "VOLVEMOS EN UN MOMENTO", "no cambies de canal", R,
      "Volvemos en un momento. No cambies de canal. BlackRose TV."),
]

# ── promos de NUESTROS programas (salen del catálogo del guion fractal) + spots de géneros: noticias 24 h, Discovery, teatro, megaconstrucciones, MTV ──
def _promos():
    try:
        sys.path.insert(0, os.path.expanduser("~/joy_vmc"))
        from director.tv.fractal import P
    except Exception as e:  # noqa: BLE001
        print("  (sin promos de programas:", e, ")"); return []
    plantillas = ["{n}. {s}. En BlackRose TV, la tele que no duerme.", "¿Te gusta lo que no sale en otros canales? {n}: {s}. Mira la cartelera.",
                  "Esta noche y todas las noches: {n}. {s}. Solo en BlackRose TV.", "{n}. {s}. No cambies de canal."]
    vis = ["holo", "dato", "memphis", "vhs", "chip", "neurona"]
    out = []
    for i, (pid, d) in enumerate(P.items()):
        if pid == "showkuroki": continue
        out.append(S("promo_" + pid, "std", vis[i % len(vis)], "doc", "EN BLACKROSE TV", d["nombre"], d["sub"], d["color"], plantillas[i % len(plantillas)].format(n=d["nombre"].title(), s=d["sub"].rstrip("."))))
    out += [
        S("g_24h", "std", "globo", "doc", "NOTICIAS 24 HORAS", "EL MUNDO NO SE DETIENE", "y nosotras tampoco", "#00e5ff", "Noticias las veinticuatro horas. Tecnología, ciencia y mundo, con foto y sin pausa. BlackRose Noticias."),
        S("g_discovery", "std", "holo", "doc", "CIENCIA", "LA CIENCIA QUE VUELA CABEZAS", "laboratorio blackrose", "#4dd2ff", "Agujeros negros, pulpos inteligentes y el ADN explicado. Laboratorio: la ciencia que vuela cabezas."),
        S("g_mega", "std", "dato", "doc", "MEGAOBRAS", "MEGACONSTRUCCIONES", "presas, torres y túneles bajo el mar", "#ffb02e", "Presas que frenan ríos, torres que tocan las nubes, túneles bajo el mar. Megaconstrucciones: cómo se levantan las obras más grandes del mundo."),
        S("g_teatro", "std", "memphis", "doc", "TEATRO", "TELÓN ARRIBA", "obras cortas, dos actrices", "#ff5e8a", "Telón arriba. Teatro BlackRose: obras cortas, dos actrices, cero presupuesto y mucho corazón."),
        S("g_mtv", "vj", "vj", "vj", "MÚSICA", "MÚSICA SIN PARAR", "libre, con créditos", "#ff2fd6", "Música sin parar. Libre, con créditos, y sin que nadie te la pida. BlackRose Music."),
        S("g_panel", "std", "marca", "doc", "PANELES", "PANEL BLACKROSE", "dos opiniones, un chat que vota", "#ff9ad5", "Paneles y debates: dos opiniones, un chat que vota, y ningún acuerdo. Equipo Joy o equipo Kuroki."),
        S("ad_grua", "ad", "sunburst", "ad", "COMERCIAL (FICTICIO)", "MEGA-GRÚAS SPA", "levantamos lo que quieras, menos tu ánimo", "#ffb02e", "¿Tu casa es muy chica? Mega-Grúas la levanta. Edificios, puentes y cohetes. Mega-Grúas: pensamos en grande, cobramos en chico.", precio="¡DESDE 49,99 CRÉDITOS!"),
        S("ad_telon", "ad", "memphis", "ad", "COMERCIAL (FICTICIO)", "TELONES EXPRESS", "dramatismo a domicilio", "#ff5e8a", "¿Necesitas un final dramático? Telones Express: cae el telón en cuarenta y ocho horas o te devolvemos tus lágrimas.", precio="¡LLAME AHORA!"),
        S("ad_pixel", "ad", "sunburst", "ad", "COMERCIAL (FICTICIO)", "PIXELES FRESCOS", "recién horneados", "#7dff6a", "Píxeles frescos: recién horneados, sin gluten y compatibles con todos los monitores. Pixeles Frescos, la textura de tu vida.", precio="¡LLEVA 2, PAGA 1,5!"),
    ]
    return out


SPOTS[-1:-1] = _promos()


async def voces():
    import edge_tts
    os.makedirs(MEDIA, exist_ok=True)
    sem = asyncio.Semaphore(4)

    async def una(s):
        voz, rate, pitch = VOCES[s["voz"]]
        f = os.path.join(MEDIA, f"{s['id']}.mp3")
        async with sem:
            await edge_tts.Communicate(s["texto"], voz, rate=rate, pitch=pitch).save(f)
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True)
        s["dur"] = round(float(out.stdout.strip() or 0), 2)
        print(f"  {s['id']:16} {s['fmt']:6} {s['voz']:5} {s['dur']:5.1f} s")

    await asyncio.gather(*(una(s) for s in SPOTS))
    json.dump([{k: v for k, v in s.items() if k != "texto"} | {"voz_mp3": f"media/{s['id']}.mp3"} for s in SPOTS],
              open(os.path.join(AQUI, "spots.json"), "w"), ensure_ascii=False, indent=1)
    print(f"  {len(SPOTS)} spots · {sum(s['dur'] for s in SPOTS):.0f} s de locución en total")


CAMAS = [   # nombre, bpm, progresión (bajo MIDI, acorde), arpegio en n-avos de tiempo, bombo en cada…
    ("cama1", 96, [(57, [57, 60, 64]), (53, [53, 57, 60]), (48, [48, 52, 55]), (55, [55, 59, 62])], 2, 2),          # Am F C G, suave
    ("cama2", 118, [(50, [50, 53, 57]), (46, [46, 50, 53]), (53, [53, 57, 60]), (48, [48, 52, 55])], 4, 1),        # Dm Bb F C, brillante
    ("cama3", 132, [(52, [52, 55, 59]), (48, [48, 52, 55]), (55, [55, 59, 62]), (50, [50, 54, 57])], 4, 1),        # Em C G D, enérgica
]


def musica():
    """Camas synthwave sintetizadas aquí (pad + arpegio + sub-bajo + bombo): sin derechos de nadie, ~24 s en bucle."""
    sr = 44100
    os.makedirs(MEDIA, exist_ok=True)
    f = lambda m: 440 * 2 ** ((m - 69) / 12)
    for nombre, bpm, prog, arp, bombo in CAMAS:
        beat = 60 / bpm
        comps = 8 if bpm < 110 else 10
        total = int(sr * beat * 4 * comps)
        y = np.zeros(total + sr)
        for c in range(comps):
            bajo, acorde = prog[c % 4]
            i0 = int(sr * beat * 4 * c)
            n = int(sr * beat * 4)
            t = np.arange(n) / sr
            env = np.minimum(1, t / 0.3) * np.minimum(1, (n / sr - t) / 0.5)
            for m in acorde:
                y[i0:i0 + n] += 0.05 * env * (np.sin(2 * np.pi * f(m) * t) + 0.5 * np.sin(2 * np.pi * f(m) * 1.004 * t))
            y[i0:i0 + n] += 0.15 * env * np.sin(2 * np.pi * f(bajo - 12) * t)
            ns = int(sr * beat / (arp / 2))
            tt = np.arange(ns) / sr
            for k in range(int(4 * arp / 2)):
                nota = acorde[k % 3] + (12 if (k // 3) % 2 else 0)
                e = np.exp(-tt * (7 if arp == 2 else 11)) * np.minimum(1, tt / 0.004)
                j = i0 + int(k * sr * beat / (arp / 2))
                y[j:j + ns] += 0.07 * e * np.sign(np.sin(2 * np.pi * f(nota + 12) * tt)) * 0.5 + 0.06 * e * np.sin(2 * np.pi * f(nota + 12) * tt)
            for k in range(0, 4, bombo):
                tk = np.arange(int(sr * 0.25)) / sr
                kick = np.sin(2 * np.pi * (50 + 90 * np.exp(-tk * 28)) * tk) * np.exp(-tk * 9)
                j = i0 + int(k * sr * beat)
                y[j:j + len(tk)] += 0.22 * kick
        y = y[:total]
        y = y / max(1e-9, np.abs(y).max()) * 0.85
        est = np.stack([y, np.roll(y, int(sr * 0.012))], axis=1)
        raw = os.path.join(MEDIA, nombre + ".raw")
        open(raw, "wb").write((est * 32767).astype("<i2").tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "2", "-i", raw, "-b:a", "128k", os.path.join(MEDIA, nombre + ".mp3")], check=True)
        os.remove(raw)
        print(f"  {nombre}.mp3 {bpm} bpm {total / sr:.0f} s")


if __name__ == "__main__":
    que = sys.argv[1] if len(sys.argv) > 1 else "todo"
    if que in ("todo", "voz"):
        asyncio.run(voces())
    if que in ("todo", "musica"):
        musica()
