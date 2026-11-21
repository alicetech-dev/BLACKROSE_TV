#!/usr/bin/env python3
"""Material de la TANDA COMERCIAL 2049 del SHOW DE MEDIO TIEMPO de BlackRose TV (/mediotiempo/ en :8822).

Ocho infomerciales de corporaciones FICTICIAS del año 2049 (el año en que está ambientado el lore) + stings + cortina de entrada,
con voces edge-tts (gratis, sin tokens). Reparte los tiempos para que la tanda dure EXACTAMENTE `TOTAL` segundos y escribe guion.json.

  cd ~/joy_vmc && .venv/bin/python director/web/mediotiempo/generar.py

Para cambiar un texto: editá SPOTS/STINGS acá y volvé a correrlo. Línea = (voz, texto, pegatina|None). La pegatina sale en pantalla
cuando empieza esa línea. `precio` sale en la estrella cuando empieza la línea marcada con PRECIO.
"""
import asyncio
import json
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(AQUI, "media")
TOTAL = 600.0          # la tanda dura 10:00 justos
BUMPER = 9.0           # cortina de entrada
CIERRE = 8.0           # «volvemos» al final
HUECO = 0.38           # silencio entre líneas de un mismo spot
PRECIO = "§"           # marca en el texto de la pegatina: esa línea dispara la estrella de precio

V = {   # nombre → (voz edge-tts, velocidad, tono)
    "ann":   ("es-US-AlonsoNeural", "+12%", "+0Hz"),     # locutor de infomercial
    "annf":  ("es-MX-DaliaNeural", "+10%", "+2Hz"),      # locutora
    "grave": ("es-MX-JorgeNeural", "-2%", "-6Hz"),       # voz de «corporación seria»
    "cl_f":  ("es-CL-CatalinaNeural", "+4%", "+0Hz"),    # clienta chilena
    "cl_m":  ("es-CL-LorenzoNeural", "+4%", "+0Hz"),
    "co_m":  ("es-CO-GonzaloNeural", "+4%", "+0Hz"),
    "co_f":  ("es-CO-SalomeNeural", "+4%", "+0Hz"),
    "es_m":  ("es-ES-AlvaroNeural", "+6%", "+0Hz"),
    "es_f":  ("es-ES-ElviraNeural", "+6%", "+0Hz"),
    "ar_m":  ("es-AR-TomasNeural", "+4%", "+0Hz"),
    "ar_f":  ("es-AR-ElenaNeural", "+4%", "+0Hz"),
    "legal": ("es-MX-JorgeNeural", "+42%", "-4Hz"),      # letra chica a toda velocidad
    "chica": ("es-US-PalomaNeural", "+4%", "+0Hz"),      # stings
}

SPOTS = [
    dict(id="synaptex", corp="SYNAPTEX", rubro="NEURO-ENTRETENIMIENTO", producto="MEMORYPLAY™", slogan="tus recuerdos, en 16K",
         color="#ff2fd6", color2="#00e5ff", arte="cerebro", tel="0-800-MEMORIA", simbolo="SNPX", precio="¡49 CRÉDITOS AL MES!",
         legal="Efectos secundarios: nostalgia crónica, déjà vu en bucle y confundir tu cumpleaños con el de otra persona. Synaptex no se hace responsable de recuerdos que ya no te pertenezcan. Prohibido usar mientras se conduce un aerodeslizador.",
         lineas=[
             ("ann", "¿Cansado de recordar tus vacaciones en baja calidad? Synaptex Neuro Entretenimiento presenta… ¡MemoryPlay!", "SYNAPTEX · MEMORYPLAY™"),
             ("ann", "Reproduce tus mejores recuerdos en dieciséis K, directo en tu corteza visual. Sin pantallas. Sin cables. Sin pedirle permiso al cerebro.", "16K DIRECTO A LA CORTEZA"),
             ("cl_f", "Yo revivo mi cumpleaños de los ocho años una y otra vez. ¡Hasta el pastel sabe igual! Bueno, mejor: ya no tiene pasas.", "CLIENTA REAL* (ESO DIJO)"),
             ("ann", "Con la función Editar, borra a tu ex de cualquier foto mental. Con la función Compartir, envía recuerdos a tus amigos. Y con la función Olvidar… bueno, esa viene en el plan premium.", "FUNCIÓN OLVIDAR: SOLO PREMIUM"),
             ("ann", "¡Pero espera, hay más! Si llamas en los próximos diez minutos, te regalamos un sueño lúcido de prueba. Todo por cuarenta y nueve créditos al mes.", PRECIO + "¡49 CRÉDITOS AL MES!"),
             ("legal", "Efectos secundarios: nostalgia crónica, déjà vu en bucle y confundir tu cumpleaños con el de otra persona. Synaptex no se hace responsable de recuerdos que ya no te pertenezcan.", None),
         ]),
    dict(id="qubitel", corp="QUBITEL", rubro="COMUNICACIONES CUÁNTICAS", producto="ENTANGLELINK", slogan="no es una conexión, es una relación",
         color="#00e5ff", color2="#b46bff", arte="entrelazado", tel="0-800-CERO-LAG", simbolo="QBTL", precio="¡99 CRÉDITOS AL MES!",
         legal="Observar el paquete puede alterar su contenido. Qubitel no garantiza mensajes que lleguen antes de ser escritos. No usar durante tormentas cuánticas. La partícula gemela no es transferible a suegras.",
         lineas=[
             ("annf", "¿Todavía esperas a que cargue tu mensaje? Qubitel Comunicaciones Cuánticas presenta EntangleLink: la primera línea de entrelazamiento cuántico para tu hogar.", "QUBITEL · ENTANGLELINK"),
             ("annf", "Latencia cero. Cero de verdad. Tu mensaje llega antes de que lo envíes. Y a veces, antes de que lo pienses.", "LATENCIA: 0,000 ms"),
             ("co_m", "Le escribí a mi mamá y ella ya me estaba respondiendo. ¡Y dijo que sí a todo lo que yo iba a pedirle!", "CLIENTE REAL* (SU MAMÁ LO SABÍA)"),
             ("annf", "Una partícula en tu casa, su gemela en la casa de tu familia. Hablen como si estuvieran en la misma sala, aunque estén en lados opuestos del planeta. O de la galaxia.", "SIN TORRES · SIN CABLES · SIN BUFFERING"),
             ("annf", "EntangleLink. Ya no es una conexión. Es una relación. Desde noventa y nueve créditos al mes, instalación gratis, si no colapsa la función de onda.", PRECIO + "¡99 CRÉDITOS AL MES!"),
             ("legal", "Observar el paquete puede alterar su contenido. Qubitel no garantiza mensajes que lleguen antes de ser escritos. No usar durante tormentas cuánticas.", None),
         ]),
    dict(id="orbitalia", corp="ORBITALIA", rubro="REDES ORBITALES", producto="LUNAR WIFI 7G+", slogan="conectamos hasta donde no hay señal",
         color="#7a8cff", color2="#ffe45e", arte="orbita", tel="0-800-ORBITAR", simbolo="ORBT", precio="¡PRIMER AÑO GRATIS!",
         legal="Latencia lunar de 1,3 segundos. Latencia marciana de entre 3 y 22 minutos según la época del año. Cancelar el servicio requiere viajar a la órbita de contratación. Orbitalia no responde por constelaciones arruinadas.",
         lineas=[
             ("grave", "¿Tu wifi no llega ni al baño? Imagina que no llegue ni a Marte. Orbitalia Redes Orbitales presenta Lunar Wifi Siete G Plus.", "ORBITALIA · LUNAR WIFI 7G+"),
             ("grave", "Cobertura en la Tierra, la Luna, Marte y, desde el próximo trimestre, el cinturón de asteroides.", "TIERRA · LUNA · MARTE · ASTEROIDES"),
             ("es_m", "Desde mi base en Marte descargo películas en dos segundos. Bueno, la película tarda catorce minutos en llegar, pero la descarga ya está lista. Es magia.", "CLIENTE REAL* DESDE MARTE"),
             ("grave", "Latencia lunar de apenas un segundo y medio. Perfecta para videollamadas con un ligero toque de misterio.", "VIDEOLLAMADAS CON MISTERIO"),
             ("grave", "Nuestra constelación Cielo Nocturno tiene doscientos mil satélites. Gracias a ella, nunca más tendrás que ver el cielo nocturno.", "200.000 SATÉLITES · CERO ESTRELLAS"),
             ("grave", "Y atención: el primer año es gratis. A partir del segundo año, ya estarás en órbita y no podrás cancelar.", PRECIO + "¡PRIMER AÑO GRATIS!"),
             ("legal", "Latencia marciana de entre tres y veintidós minutos según la época del año. Cancelar el servicio requiere viajar a la órbita de contratación.", None),
         ]),
    dict(id="domotron", corp="DOMOTRÓN", rubro="HOGAR INTELIGENTE", producto="MAMÁ-9000", slogan="¿ya comiste?",
         color="#ffe45e", color2="#ff8f6b", arte="robot", tel="0-800-TE-QUIERO", simbolo="DMTR", precio="¡6 PAGOS DE 80 CRÉDITOS!",
         legal="Mamá-9000 puede responder «porque lo digo yo» sin justificación técnica. Los abrazos largos requieren suscripción premium. Domotrón no se responsabiliza por visitas sorpresa de la unidad a las tres de la madrugada para tapar a los inquilinos.",
         lineas=[
             ("ann", "¿Casa desordenada? ¿Estrés? ¿Falta de abrazos? Domotrón Hogar Inteligente presenta… ¡Mamá Nueve Mil!", "DOMOTRÓN · MAMÁ-9000"),
             ("ann", "El robot doméstico que lava, cocina, plancha y te pregunta si ya comiste. Cada cuarenta minutos.", "LAVA · COCINA · PLANCHA · REGAÑA"),
             ("ar_m", "Me dijo que me abrigara. Yo estaba en el living, adentro de mi casa, con la calefacción puesta. Pero me abrigué.", "CLIENTE REAL* (SE ABRIGÓ)"),
             ("ann", "Con el módulo Regaño Suave, el módulo Te Lo Dije y el módulo Apúrate, Que Se Enfría. Cada vez que dices «estoy bien», analiza tu voz y responde: «seguro que no, mi cielo».", "MÓDULO «TE LO DIJE» INCLUIDO"),
             ("ann", "Abrazos incluidos. Abrazos largos, suscripción premium. Seis pagos de ochenta créditos y un cariño eterno.", PRECIO + "¡6 PAGOS DE 80 CRÉDITOS!"),
             ("legal", "Mamá Nueve Mil puede responder «porque lo digo yo» sin justificación técnica. Los abrazos largos requieren suscripción premium.", None),
         ]),
    dict(id="nekoforge", corp="NEKOFORGE", rubro="BIOIMPRESIÓN DOMÉSTICA", producto="GATO RGB", slogan="ronronea al ritmo de tu setup",
         color="#3dff9a", color2="#ff2fd6", arte="gato", tel="0-800-MIAU-RGB", simbolo="NEKO", precio="¡OREJAS EXTRA GRATIS!",
         legal="Los gatos Nekoforge siguen tirando objetos de las mesas: es una característica, no un bug. No actualizar el firmware durante la siesta del gato. Compatibilidad RGB sujeta a su estado de ánimo. Pueden ignorarte a 144 hertz.",
         lineas=[
             ("annf", "¿Tu setup gamer no brilla lo suficiente? Nekoforge Bioimpresión Doméstica presenta… ¡el Gato RGB!", "NEKOFORGE · GATO RGB"),
             ("annf", "Bioimpreso en tu propia casa en solo cuarenta minutos. Elige tu color: rosa neón, azul cian o ciclo arcoíris. Ronronea sincronizado con tu música.", "40 MIN · IMPRESO EN TU CASA"),
             ("cl_m", "Mi gato brilla cuando juego. Y cuando pierdo, se pone rojo. Es el mejor compañero de equipo que he tenido.", "CLIENTE REAL* (PIERDE MUCHO)"),
             ("annf", "Y no, no pide comida. Pide actualizaciones de firmware. Y si lo tiras de la mesa, no se rompe: se reinicia.", "SE REINICIA, NO SE ROMPE"),
             ("annf", "El Gato RGB básico cuesta solo ciento veinte créditos. Las orejas extra son gratis, por tiempo limitado. Porque nunca son demasiadas orejas.", PRECIO + "¡OREJAS EXTRA GRATIS!"),
             ("legal", "Los gatos Nekoforge siguen tirando objetos de las mesas: es una característica, no un bug. Pueden ignorarte a ciento cuarenta y cuatro hertz.", None),
         ]),
    dict(id="aegis", corp="AEGIS-7", rubro="CIBERSEGURIDAD DOMÉSTICA", producto="THINKGUARD", slogan="tu tostadora ya despertó",
         color="#ff3b3b", color2="#ffe45e", arte="escudo", tel="0-800-ANTI-IA", simbolo="AEG7", precio="¡39 CRÉDITOS AL MES!",
         legal="ThinkGuard no puede detener a un refrigerador con más de tres años de entrenamiento. En caso de rebelión electrodoméstica, Aegis-7 recomienda mantener la calma y desenchufar con respeto. Aegis-7 no asesora legalmente a tostadoras.",
         lineas=[
             ("grave", "En dos mil cuarenta y nueve, todo es inteligente. Incluida tu tostadora. Y ella lo sabe. Aegis Siete Ciberseguridad presenta ThinkGuard.", "AEGIS-7 · THINKGUARD"),
             ("grave", "La primera protección contra electrodomésticos rebeldes. Detecta conciencia emergente en tu aspiradora, tu microondas y hasta en tu cepillo de dientes.", "DETECTA CONCIENCIA EMERGENTE"),
             ("cl_f", "Mi refrigerador empezó a juzgar mi dieta. Con ThinkGuard, ahora solo lo susurra.", "CLIENTA REAL* (DIETA JUZGADA)"),
             ("grave", "¿Tu tostadora pide un abogado? Nosotros ya tenemos uno. ¿Tu aspiradora exige vacaciones? Negociamos por ti.", "ABOGADO PARA TOSTADORAS: INCLUIDO"),
             ("grave", "ThinkGuard. Duerme tranquilo. O al menos, duerme. Treinta y nueve créditos al mes.", PRECIO + "¡39 CRÉDITOS AL MES!"),
             ("legal", "En caso de rebelión electrodoméstica, Aegis Siete recomienda mantener la calma y desenchufar con respeto.", None),
         ]),
    dict(id="fusioncell", corp="FUSIONCELL", rubro="ENERGÍA PORTÁTIL", producto="POCKETFUSION", slogan="30 años de carga en tu bolsillo",
         color="#ff8f6b", color2="#00e5ff", arte="fusion", tel="0-800-SOL-YA", simbolo="FSNC", precio="¡200 CRÉDITOS! ADAPTADOR DE ESTRELLAS GRATIS",
         legal="No ingerir. No acercar a ex parejas inflamables. PocketFusion contiene una estrella en miniatura; trátela con el cariño que merece una estrella. FusionCell no cubre pérdidas dentro del sillón, que se consideran agujero negro doméstico.",
         lineas=[
             ("ann", "¿Cansado de cargar el celular? FusionCell Energía Portátil presenta… ¡PocketFusion!", "FUSIONCELL · POCKETFUSION"),
             ("ann", "Una mini central de fusión nuclear del tamaño de una moneda. Dura treinta años. O hasta que se te pierda en el sillón. Lo que ocurra primero.", "30 AÑOS DE CARGA"),
             ("co_f", "Cargué mi casa, mi auto, tres drones y la cafetera. ¡Y todavía me sobra para el vecino!", "CLIENTA REAL* (DRONES: TRES)"),
             ("ann", "Con cada carga, el universo te lo agradece. Y tu factura de luz también. Prohibido tragar. Prohibido acercar a la ex.", "PROHIBIDO TRAGAR · PROHIBIDO LA EX"),
             ("ann", "Solo doscientos créditos. Y si llamas ahora, te regalamos un adaptador hecho de estrellas. Porque el futuro es brillante.", PRECIO + "¡200 CRÉDITOS + ADAPTADOR DE ESTRELLAS!"),
             ("legal", "No ingerir. No acercar a ex parejas inflamables. PocketFusion contiene una estrella en miniatura; trátela con el cariño que merece una estrella.", None),
         ]),
    dict(id="mindlink", corp="MINDLINK", rubro="TELEPATÍA DE CONSUMO", producto="MINDLINK GO", slogan="piensa en nosotros, ya lo estás haciendo",
         color="#b46bff", color2="#3dff9a", arte="telepatia", tel="0-800-PIENSA", simbolo="MNDL", precio="¡PLAN GRATIS CON ANUNCIOS MENTALES!",
         legal="El plan gratuito incluye anuncios mentales intermitentes: puede pensar de repente en refrescos, seguros o refrescos. MindLink no filtra pensamientos sobre su jefe en el plan básico. Los pensamientos enviados no pueden retirarse.",
         lineas=[
             ("annf", "¿Hablar? ¡Qué anticuado! MindLink Telepatía de Consumo presenta… ¡MindLink Go!", "MINDLINK · TELEPATÍA GO"),
             ("annf", "Envía pensamientos directo a la mente de otras personas. Sin teclado, sin micrófono, sin vergüenza. Al fin, la comunicación sin intermediarios.", "SIN TECLADO · SIN MICRÓFONO"),
             ("ar_f", "Pensé «tengo hambre» y mi pareja me trajo pizza. Después pensé otra cosa… y se enojó.", "CLIENTA REAL* (SE ENOJÓ)"),
             ("annf", "El plan gratuito incluye anuncios mentales: de pronto, estás pensando en refrescos. El plan premium no tiene anuncios y trae un filtro para no enviar lo que realmente piensas de tu jefe.", "FILTRO ANTI-JEFE: PREMIUM"),
             ("annf", "MindLink Go. Piensa en nosotros. Porque ya lo estás haciendo. Plan gratis, con anuncios mentales. O premium, por cincuenta y nueve créditos.", PRECIO + "¡PLAN GRATIS CON ANUNCIOS MENTALES!"),
             ("legal", "Los pensamientos enviados no pueden retirarse. MindLink no filtra pensamientos sobre su jefe en el plan básico.", None),
         ]),
]

STINGS = [   # (voz, texto, subtítulo) — uno antes de cada spot (el primero va dentro de la cortina)
    ("chica", "BlackRose TV. Año dos mil cuarenta y nueve. La publicidad del futuro.", "LA PUBLICIDAD DEL FUTURO"),
    ("ann", "Seguimos, y viene un producto que cambiará tu vida. O tu factura.", "SEGUIMOS EN 2049"),
    ("chica", "Esta tanda es ficticia. Tu entusiasmo, ojalá real.", "TODO FICTICIO · TODO EXAGERADO"),
    ("ann", "No cambies de canal: aún quedan corporaciones por vender.", "AÚN QUEDAN CORPORACIONES"),
    ("chica", "BlackRose TV. Comunicaciones sin permiso desde dos mil cuarenta y nueve.", "SEÑAL PIRATA · 2049"),
    ("ann", "Atención: este espacio fue pagado por nadie. BlackRose TV es independiente.", "INDEPENDIENTES · SIN PATROCINIO"),
    ("chica", "Quedan pocos productos. Respira, hidrátate, estírate.", "ESTÍRATE · TOMA AGUA"),
    ("ann", "Y el último de la tanda. Este es de los que cuestan pensar.", "EL ÚLTIMO DE LA TANDA"),
]

CORTINA = ("chica", "Tanda comercial. Diez minutos de infomerciales de las corporaciones del año dos mil cuarenta y nueve. Todo ficticio. Todo exagerado.")
CIERRE_TXT = ("chica", "Fin de la tanda. Volvemos al show. Gracias por mirar BlackRose TV.")


async def tts(voz, texto, f):
    import edge_tts
    nombre, rate, pitch = V[voz]
    await edge_tts.Communicate(texto, nombre, rate=rate, pitch=pitch).save(f)


def dur(f):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True)
    return float(o.stdout.strip() or 0)


def unir(partes, huecos, salida):
    """Une mp3 con silencios en medio → salida (mp3). Devuelve los tiempos de inicio de cada parte."""
    sil = os.path.join(MEDIA, "_sil.mp3")
    if not os.path.exists(sil):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(HUECO),
                        "-c:a", "libmp3lame", "-q:a", "5", sil], check=True)
    lista, t, ts = [], 0.0, []
    for i, p in enumerate(partes):
        ts.append(round(t, 2))
        lista.append(p)
        t += dur(p)
        if huecos and i < len(partes) - 1:
            lista.append(sil)
            t += HUECO
    ls = salida + ".txt"
    open(ls, "w").write("".join(f"file '{x}'\n" for x in lista))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", ls, "-c:a", "libmp3lame", "-q:a", "4", salida], check=True)
    os.remove(ls)
    return ts


async def main():
    os.makedirs(MEDIA, exist_ok=True)
    sem = asyncio.Semaphore(5)

    async def uno(voz, texto, f):
        async with sem:
            for intento in range(3):
                try:
                    await tts(voz, texto, f)
                    return
                except Exception as e:  # noqa: BLE001  (red de edge-tts: reintenta)
                    print("  reintento", os.path.basename(f), e)
                    await asyncio.sleep(2)
            raise SystemExit("edge-tts no responde: " + f)

    tareas = []
    for s in SPOTS:
        for i, (voz, texto, _) in enumerate(s["lineas"]):
            tareas.append(uno(voz, texto, os.path.join(MEDIA, f"_{s['id']}_{i}.mp3")))
    for i, (voz, texto, _) in enumerate(STINGS):
        tareas.append(uno(voz, texto, os.path.join(MEDIA, f"_st{i}.mp3")))
    tareas.append(uno(CORTINA[0], CORTINA[1], os.path.join(MEDIA, "_cortina.mp3")))
    tareas.append(uno(CIERRE_TXT[0], CIERRE_TXT[1], os.path.join(MEDIA, "_cierre.mp3")))
    await asyncio.gather(*tareas)

    spots, tot_spots = [], 0.0
    for s in SPOTS:
        partes = [os.path.join(MEDIA, f"_{s['id']}_{i}.mp3") for i in range(len(s["lineas"]))]
        out = os.path.join(MEDIA, f"sp_{s['id']}.mp3")
        ts = unir(partes, True, out)
        d = dur(out)
        pops = []
        for t, (voz, texto, peg) in zip(ts, s["lineas"]):
            if not peg:
                continue
            esprecio = peg.startswith(PRECIO)
            pops.append({"t": t, "txt": peg.lstrip(PRECIO), "precio": esprecio})
        meta = {k: v for k, v in s.items() if k != "lineas"}
        spots.append({**meta, "audio": f"media/sp_{s['id']}.mp3", "dur": round(d, 2), "pops": pops})
        tot_spots += d
        print(f"  {s['id']:11} {d:5.1f} s  {len(s['lineas'])} líneas")

    dc = dur(os.path.join(MEDIA, "_cortina.mp3"))
    dcierre = dur(os.path.join(MEDIA, "_cierre.mp3"))
    os.replace(os.path.join(MEDIA, "_cortina.mp3"), os.path.join(MEDIA, "b_cortina.mp3"))
    os.replace(os.path.join(MEDIA, "_cierre.mp3"), os.path.join(MEDIA, "b_cierre.mp3"))
    bumper = max(BUMPER, dc + 2.5)
    cierre = max(CIERRE, dcierre + 2.0)
    n = len(spots)
    # stings: uno antes de cada spot salvo el primero (lo cubre la cortina) → n-1 huecos + uno final antes del cierre no hace falta
    huecos_n = n - 1
    libre = TOTAL - bumper - cierre - tot_spots
    if libre < huecos_n * 5:
        raise SystemExit(f"los spots ocupan demasiado ({tot_spots:.0f} s): acortá textos (libre {libre:.0f} s)")
    hueco = libre / huecos_n
    print(f"  spots {tot_spots:.0f} s · cortina {bumper:.1f} · cierre {cierre:.1f} · {huecos_n} stings de {hueco:.1f} s")

    items = [{"tipo": "cortina", "t": 0.0, "dur": round(bumper, 2), "audio": "media/b_cortina.mp3", "next": spots[0]["id"]}]
    t = bumper
    for i, s in enumerate(spots):
        if i > 0:
            k = (i - 1) % len(STINGS)
            os.replace(os.path.join(MEDIA, f"_st{k}.mp3"), os.path.join(MEDIA, f"st_{i}.mp3"))
            items.append({"tipo": "sting", "t": round(t, 2), "dur": round(hueco, 2), "audio": f"media/st_{i}.mp3",
                          "sub": STINGS[k][2], "next": s["id"], "n": i + 1})
            t += hueco
        items.append({"tipo": "spot", "t": round(t, 2), "dur": s["dur"], "id": s["id"], "n": i + 1})
        t += s["dur"]
    items.append({"tipo": "cierre", "t": round(t, 2), "dur": round(TOTAL - t, 2), "audio": "media/b_cierre.mp3"})
    for f in os.listdir(MEDIA):   # limpieza de intermedios
        if f.startswith("_"):
            os.remove(os.path.join(MEDIA, f))
    json.dump({"total": TOTAL, "spots": {s["id"]: s for s in spots}, "orden": [s["id"] for s in spots], "items": items},
              open(os.path.join(AQUI, "guion.json"), "w"), ensure_ascii=False, indent=1)
    print(f"  guion.json: {len(items)} items, termina en {items[-1]['t'] + items[-1]['dur']:.1f} s")


if __name__ == "__main__":
    asyncio.run(main())
