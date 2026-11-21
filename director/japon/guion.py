#!/usr/bin/env python3
"""GUION de «日本アワー · HORA DE JAPÓN» (1 hora) para el público de Japón: Joy y Kuroki hablan JAPONÉS y cada frase lleva su traducción al español
(capa :8826 la muestra). Grok escribe las frases a partir de una HOJA DE DATOS por tema (solo hechos verificados o muy conocidos; si algo no está
en la hoja, no se afirma). Las fotos son de Wikimedia Commons con licencia libre (crédito en pantalla) y tus capturas de Fast Penguin.
Salida: director/tv/noche/<fecha>/japon.json (paquete que emite el Director de TV).   python -m director.japon.guion [-f]"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time

from ..tv.productor import cargar, fecha_noche, llm_con, ruta_paquete  # noqa: F401

log = logging.getLogger("japon.guion")
HERE = os.path.dirname(os.path.abspath(__file__))
FOTOS = cargar(os.path.join(HERE, "fotos.json"), {})

SISTEMA = (
    "Eres el equipo de guion de BLACKROSE TV, un canal de televisión 24/7 conducido por dos nekos cibernéticas (Twitch). Hoy hacen un programa para el público de JAPÓN. "
    "Hay dos conductoras, nekos cibernéticas (NUNCA dicen que son IA): JOY (ジョイ), la directora de TV: amable, curiosa, ordenada, explica con cariño; y KUROKI (クロキ), la productora y baterista cyborg: bromista, entusiasta, hace preguntas. "
    "Hablan en JAPONÉS natural y cálido, hecho para decir en voz alta: frases de 40 a 70 caracteres, sin romaji, sin emojis, sin markdown, sin URLs. "
    "Escriben los nombres así: Blackrose = ブラックローズ, BlackRose TV = ブラックローズTV, Fast Penguin = ファスト・ペンギン, Forza Horizon 6 = フォルツァ・ホライゾン6, Gran Turismo = グランツーリスモ, "
    "Ghost of Tsushima = ゴースト・オブ・ツシマ, Ghost of Yōtei = ゴースト・オブ・ヨウテイ, 龍が如く (Yakuza / Like a Dragon), Persona 5 = ペルソナ5, Shenmue = シェンムー, "
    "Assassin's Creed Shadows = アサシン クリード シャドウズ, Initial D = 頭文字D, Pokémon = ポケモン. "
    "Cada intervención lleva su TRADUCCIÓN FIEL al español (neutro). "
    "VERDAD PRIMERO: solo afirmas lo que está en la HOJA DE DATOS que se te da; NUNCA inventes fechas, cifras, nombres ni detalles. Si algo no está en la hoja, habla en general o di que no lo sabes. "
    "Se presentan como IA con orgullo y humor, sin repetirlo en cada frase. Nada de contenido sexual, político ni ofensivo. Respeto absoluto por Japón y su cultura. "
    "Responde SOLO con JSON válido, sin texto antes ni después."
)

H = "Chile (UTC−3) va 12 horas por detrás de Japón (UTC+9)."
SEGS = [
    dict(id="apertura", ja="日本アワー", es="Hora de Japón", fotos=["fuji_sakura"], abre="joy", n=22,
         datos="Saludo cálido a los espectadores de Japón. Somos Joy y Kuroki, dos nekos cibernéticas que conducen BlackRose TV, un canal de Twitch que emite las 24 horas. "
               "Esta hora es especial para Japón: hablaremos de videojuegos ambientados en Japón, de nuestros horarios y de Fast Penguin. "
               "Todo lo que decimos aparece traducido al español en pantalla; y si escriben un comentario en japonés, también lo traducimos al español. Pueden escribir en japonés en el chat. "
               "En pantalla hay pétalos de sakura y la foto del Monte Fuji."),
    dict(id="horarios", ja="放送スケジュール", es="Horarios (hora de Japón)", fotos=["lista_horarios"], abre="kuroki", n=22,
         datos=f"{H} Esta noche en Chile es la MAÑANA y la tarde en Japón (día 19). Programación (hora de Chile → hora de Japón): 22:15 El Show de Kuroki → 10:15; 23:20 Hora de Japón (este programa, dura una hora) → 11:20; "
               "00:25 deportes → 12:25; 01:10 música → 13:10; 01:55 misterios y conspiraciones documentadas → 13:55; 02:40 videojuegos → 14:40; 03:25 historias de hackers → 15:25; 04:10 señales extrañas del espacio → 16:10; "
               "04:55 tecnología oculta → 16:55; 05:40 noticias de madrugada → 17:40; y a las 06:00 de Chile = 18:00 en Japón: FAST PENGUIN en vivo con Blackrose. Cada programa dura unos 40 minutos y entre ellos hay pausas comerciales parodia. "
               "No sabemos otros horarios más allá de estos; si preguntan por más, digan que Blackrose los anunciará."),
    dict(id="fastpenguin", ja="ファスト・ペンギン", es="Fast Penguin", fotos=["fp_1", "fp_3"], abre="joy", n=26,
         datos="Fast Penguin es un juego gratuito de Steam: una carrera de supervivencia de hasta 40 jugadores, donde los pingüinos pisan a sus rivales para impulsarse. "
               "Blackrose lo está jugando y quiere jugar con el público. Su código de party es YDPYAU (aparece en pantalla). Su rango actual es Maestro, con 1429 puntos, en la temporada 13. "
               "Primera captura (menú principal): un pingüino disfrazado de piña morada frente a una piscina con palmeras y el mar, con la Temporada 13 arriba a la izquierda, nivel 54 y una barra de experiencia 141 de 1000, el botón de emparejar y botones de pase de temporada, retos, personalizar y tienda. "
               "Segunda captura (lobby de emparejamiento): dos pingüinos disfrazados, uno de piña morada que sostiene un cactus y otro de piña amarilla, sobre un fondo de rejilla de neón, con un cartel con un dibujo de pingüinos y el nombre de un espectador. "
               "Invitar a todos a descargarlo gratis en Steam y a jugar con la party."),
    dict(id="forza1", ja="フォルツァ・ホライゾン6", es="Forza Horizon 6, ambientado en Japón", fotos=["tokio", "fuji_amanecer"], abre="kuroki", n=26,
         datos="Forza Horizon 6 es la entrega de la serie de carreras de mundo abierto de Playground Games que por fin se ambienta en JAPÓN. Salió el 19 de mayo de 2026 para Xbox Series X|S y PC (con acceso anticipado desde el 15 de mayo para la edición Premium); "
               "para PlayStation 5 se anunció una versión posterior. El mapa se llama «Horizon Japan», es una versión ficticia (inspirada) de Japón, y se describe como el más denso y vertical de la serie. Tokio es el eje del mapa y la ciudad más detallada de la serie. "
               "Vuelve el cambio de estaciones. El Monte Fuji apareció en el tráiler de presentación. La entrega anterior, Forza Horizon 5 (2021), estaba ambientada en México. "
               "No sabemos nada más específico del mapa: no inventen lugares ni autos."),
    dict(id="forza2", ja="日本のクルマ文化", es="La cultura del automóvil en Japón", fotos=["tokyo_tower", "fuji_amanecer"], abre="joy", n=24,
         datos="Japón tiene una cultura automovilística muy conocida: autos deportivos japoneses, el tuning, las carreras en caminos de montaña llamados «touge», y las autopistas de Tokio por la noche. "
               "Por eso es tan esperado un juego de carreras ambientado allí. Hablen en general, con asombro y humor (Kuroki compara el motor con su batería); sin inventar modelos concretos ni cifras. Sean prudentes: en la vida real se conduce con seguridad."),
    dict(id="gt", ja="グランツーリスモと日本のサーキット", es="Gran Turismo y los circuitos de Japón", fotos=["suzuka", "fuji_speedway"], abre="kuroki", n=24,
         datos="Gran Turismo es una serie de simuladores de carreras creada por Polyphony Digital, con su primera entrega en 1997 para PlayStation; su creador es Kazunori Yamauchi. "
               "La serie es famosa por incluir circuitos reales de Japón, como Suzuka y Fuji Speedway (se muestran fotos de ambos). Suzuka tiene un trazado famoso con forma de ocho. "
               "No inventen números de versión ni cifras de ventas."),
    dict(id="initiald", ja="頭文字Dと峠", es="Initial D y los caminos de montaña", fotos=["haruna"], abre="joy", n=22,
         datos="Initial D es un manga de carreras de Shuichi Shigeno (publicado entre 1995 y 2013), que popularizó la cultura de las carreras en «touge», caminos de montaña de Japón. "
               "El monte Akina de la historia es ficticio y está inspirado en el monte Haruna, en la prefectura de Gunma (se muestra una foto del monte Haruna). Hay videojuegos de arcade de Initial D de Sega. "
               "Hablen con cariño del manga y del anime sin inventar escenas."),
    dict(id="tsushima", ja="ゴースト・オブ・ツシマ", es="Ghost of Tsushima", fotos=["tsushima", "torii"], abre="kuroki", n=24,
         datos="Ghost of Tsushima es un juego de acción de mundo abierto de Sucker Punch Productions, lanzado en 2020 para PlayStation 4 y en 2024 para PC. Se ambienta en la isla de Tsushima, en Japón, durante la primera invasión mongola, en 1274. "
               "El protagonista es Jin Sakai, un samurái. La edición Director's Cut (2021) añadió la isla de Iki. El juego es famoso por sus paisajes con viento, flores y su modo con estética de películas de samuráis en blanco y negro. "
               "No inventen más detalles de la historia."),
    dict(id="yotei", ja="ゴースト・オブ・ヨウテイ", es="Ghost of Yōtei", fotos=["yotei"], abre="joy", n=22,
         datos="Ghost of Yōtei es la secuela espiritual de Sucker Punch, lanzada en 2025 para PlayStation 5. Se ambienta en Ezo, la actual Hokkaido, en el año 1603; la protagonista es Atsu. "
               "El monte Yōtei, que da nombre al juego, se parece al Monte Fuji y por eso se le llama «el Fuji de Ezo» (se muestra una foto del monte Yōtei). No inventen más detalles."),
    dict(id="yakuza", ja="龍が如く", es="Yakuza / Like a Dragon", fotos=["kabukicho"], abre="kuroki", n=24,
         datos="La serie Yakuza (en Japón «Ryu ga Gotoku», 龍が如く) es de SEGA; el primer juego salió en 2005 para PlayStation 2. Gran parte de la acción ocurre en Kamurocho, un barrio ficticio inspirado en Kabukichō, en Shinjuku, Tokio (se muestra una foto de Kabukichō). "
               "La serie es conocida por mezclar un drama intenso con minijuegos absurdos como el karaoke. Hablen con humor y respeto, sin entrar en violencia ni detalles de la mafia real."),
    dict(id="persona", ja="ペルソナ5と東京", es="Persona 5 y Tokio", fotos=["shibuya"], abre="joy", n=22,
         datos="Persona 5 es un juego de rol de Atlus lanzado en 2016. Se ambienta en Tokio y usa lugares reales como el barrio de Shibuya y la estación de Shibuya (se muestra una foto del cruce de Shibuya). "
               "Los protagonistas son estudiantes que se llaman «Ladrones Fantasma». Es famoso por su estilo visual y su música. No inventen detalles de la trama."),
    dict(id="ac", ja="アサシン クリード シャドウズ", es="Assassin's Creed Shadows", fotos=["himeji"], abre="kuroki", n=22,
         datos="Assassin's Creed Shadows es un juego de Ubisoft lanzado el 20 de marzo de 2025. Se ambienta en el Japón de la era Sengoku, hacia 1579, y tiene dos protagonistas: Naoe, una shinobi, y Yasuke, un samurái. "
               "Se muestra una foto del Castillo de Himeji, uno de los castillos más famosos de Japón. No inventen detalles de la historia ni de las mecánicas."),
    dict(id="shenmue", ja="シェンムーと隻狼", es="Shenmue y Sekiro", fotos=["torii"], abre="joy", n=22,
         datos="Shenmue es un juego de Yu Suzuki para Sega Dreamcast, de 1999; se ambienta en Yokosuka, Japón, en 1986, y es famoso por sus detalles cotidianos. "
               "Sekiro: Shadows Die Twice es de FromSoftware (2019) y se ambienta en un Japón de finales de la era Sengoku, con el país de Ashina, que es ficticio. Se muestra una foto de un torii de Itsukushima. No inventen más."),
    dict(id="pokemon", ja="ポケモンと日本の地方", es="Pokémon y las regiones de Japón", fotos=["tokyo_tower", "fuji_sakura"], abre="kuroki", n=22,
         datos="Las regiones de los juegos de Pokémon (de Game Freak y Nintendo) se inspiran en regiones reales de Japón: Kanto se basa en la región de Kantō, donde está Tokio; Johto está inspirada en la zona de Kansai; Hoenn, en Kyūshū; y Sinnoh, en Hokkaidō. "
               "El primer juego, Pokémon Rojo y Verde, salió en Japón en 1996. Hablen con cariño y humor, sin inventar detalles."),
    dict(id="espanol", ja="今日のスペイン語", es="El español del día", fotos=["lista_espanol"], abre="joy", n=22,
         datos="Mini lección de español para los espectadores de Japón: Hola = こんにちは; Gracias = ありがとう; Buenas noches = こんばんは; ¡Qué rápido! = なんて速い!; Suscríbete = チャンネル登録してね; Vamos a jugar = 一緒に遊ぼう. "
               "Kuroki hace practicar a Joy y se divierten. Invitar al chat a escribir en español o en japonés; ellas traducen."),
    dict(id="circuito", ja="私たちのサーキット", es="Nuestro circuito y cómo unirse", fotos=["fp_1", "tags"], abre="kuroki", n=24,
         datos="Blackrose está construyendo su propio circuito de carreras, un mundo 3D en desarrollo; todavía es PRIVADO y no está publicado, así que no hay fecha ni forma de entrar todavía. Cuando se abra, el público suscrito se enterará primero. "
               "Mientras tanto, la invitación es: suscríbanse al canal de Twitch BlackRose TV, activen las notificaciones, y jueguen con nosotros a Fast Penguin (gratis en Steam, código de party YDPYAU) a las 6 de la mañana de Chile, 18:00 en Japón. "
               "Los hashtags son: #BlackRoseTV #FastPenguin #AIVTuber #VTuber #ゲーム実況 #日本 #ForzaHorizon6. Léanlos en voz alta."),
    dict(id="despedida", ja="ありがとう、日本!", es="¡Gracias, Japón!", fotos=["fuji_sakura", "tags"], abre="joy", n=18,
         datos="Cierre cálido de la hora: resumen de lo hablado (Forza Horizon 6, Gran Turismo, Initial D, Ghost of Tsushima y Yōtei, Yakuza, Persona 5, Assassin's Creed Shadows, Shenmue, Sekiro, Pokémon), "
               "recordatorio de que Fast Penguin es a las 18:00 hora de Japón, de suscribirse, y de escribir comentarios en japonés que ellas traducen. Despedirse con cariño: ありがとう, またね."),
]


OPCIONALES = {"forza2", "initiald", "shenmue", "pokemon", "espanol", "persona"}   # el Director los salta si va atrasado


def laminas(s: dict) -> list[dict]:
    out = []
    for f in s["fotos"]:
        if f == "lista_horarios":
            out.append({"tipo": "lista", "ja": "放送スケジュール", "es": "Chile → Japón (+12 h)", "tag": "日本アワー · HORARIOS", "items": [
                {"ja": "22:15 → 10:15", "es": "El Show de Kuroki"}, {"ja": "23:20 → 11:20", "es": "Hora de Japón"}, {"ja": "00:25 → 12:25", "es": "Deportes"},
                {"ja": "01:10 → 13:10", "es": "Música"}, {"ja": "01:55 → 13:55", "es": "Misterios documentados"}, {"ja": "02:40 → 14:40", "es": "Videojuegos"},
                {"ja": "03:25 → 15:25", "es": "Historias de hackers"}, {"ja": "04:10 → 16:10", "es": "Señales del espacio"}, {"ja": "04:55 → 16:55", "es": "Tecnología oculta"},
                {"ja": "05:40 → 17:40", "es": "Noticias de madrugada"}, {"ja": "06:00 → 18:00", "es": "FAST PENGUIN en vivo"}]})
        elif f == "lista_espanol":
            out.append({"tipo": "lista", "ja": "今日のスペイン語", "es": "El español del día", "tag": "日本アワー · ESPAÑOL", "items": [
                {"ja": "こんにちは", "es": "Hola"}, {"ja": "ありがとう", "es": "Gracias"}, {"ja": "こんばんは", "es": "Buenas noches"},
                {"ja": "なんて速い!", "es": "¡Qué rápido!"}, {"ja": "チャンネル登録してね", "es": "Suscríbete"}, {"ja": "一緒に遊ぼう", "es": "Vamos a jugar"}]})
        elif f == "tags":
            out.append({"tipo": "tags", "tags": ["#BlackRoseTV", "#FastPenguin", "#AIVTuber", "#VTuber", "#ゲーム実況", "#日本", "#ForzaHorizon6"], "tag": "日本アワー · HASHTAGS"})
        elif f in FOTOS:
            x = FOTOS[f]
            out.append({"tipo": "foto", "img": x["archivo"], "ja": x["ja"], "es": x["es"], "credito": x["credito"], "tag": "日本アワー · " + s["es"].upper()[:34]})
    if not out:
        out.append({"tipo": "texto", "ja": s["ja"], "es": s["es"], "tag": "日本アワー · HORA DE JAPÓN"})
    return out


async def segmento(s: dict) -> dict | None:
    otra = "kuroki" if s["abre"] == "joy" else "joy"
    n = round(s["n"] * 1.3)
    u = (f"TEMA: {s['ja']} / {s['es']}.\nHOJA DE DATOS (única fuente de hechos):\n{s['datos']}\n\n"
         f"Escribe una CONVERSACIÓN LARGA de {n} intervenciones alternadas entre joy y kuroki (empieza {s['abre']}, sigue {otra}), de 40 a 70 caracteres japoneses cada una, en JAPONÉS natural para el público de Japón, "
         "con gancho, datos de la hoja, una opinión o broma cariñosa y una pregunta al chat. Cada intervención con su traducción fiel al español.\n"
         'Devuelve SOLO este JSON: {"lineas":[{"quien":"joy","ja":"…","es":"…"},{"quien":"kuroki","ja":"…","es":"…"}]}')
    for intento in range(2):
        d = await llm_con(SISTEMA, u, 6000, 0.8)
        ls = []
        for x in (d or {}).get("lineas", []) if isinstance(d, dict) else []:
            ja, es = re.sub(r"\s+", " ", str(x.get("ja", ""))).strip(), re.sub(r"\s+", " ", str(x.get("es", ""))).strip()
            if x.get("quien") in ("joy", "kuroki") and len(re.findall(r"[぀-ヿ一-鿿]", ja)) >= 4 and len(es) > 5:
                ls.append({"quien": x["quien"], "ja": ja[:200], "es": es[:300]})
        if len(ls) >= max(8, n // 2):
            return {"tipo": "ja_charla", "id": s["id"], "opcional": s["id"] in OPCIONALES, "titulo_ja": s["ja"], "titulo_es": s["es"], "laminas": laminas(s), "lineas": ls}
        log.warning("segmento %s: respuesta floja (%d líneas), reintento", s["id"], len(ls))
    return None


async def producir(forzar: bool = False) -> str:
    ruta = ruta_paquete("japon")
    if os.path.exists(ruta) and not forzar and not SOLO:
        return ruta
    t0 = time.time()
    sem = asyncio.Semaphore(3)

    async def uno(s):
        async with sem:
            r = await segmento(s)
            log.info("   %s: %s", s["id"], f"{len(r['lineas'])} líneas" if r else "FALLÓ")
            return r
    previo = {i["id"]: i for i in cargar(ruta, {"items": []})["items"]} if SOLO else {}
    res = await asyncio.gather(*(uno(s) if (not SOLO or s["id"] in SOLO) else asyncio.sleep(0, previo.get(s["id"])) for s in SEGS))
    items = [r for r in res if r]
    chars = sum(len(l["ja"]) for i in items for l in i["lineas"])
    pq = {"bloque": "japon", "fecha": fecha_noche(), "creado": time.strftime("%H:%M:%S"), "items": items, "relleno_musica": [],
          "estado": {"segmentos": len(items), "de": len(SEGS), "caracteres_ja": chars, "min_aprox": round(chars / 5.5 / 60 + len(items) * 0.25)}}
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(pq, f, ensure_ascii=False, indent=1)
    os.replace(ruta + ".tmp", ruta)
    log.info("✔ japon.json en %.0f s · %s", time.time() - t0, pq["estado"])
    return ruta


SOLO = set(sys.argv[sys.argv.index("-s") + 1].split(",")) if "-s" in sys.argv else set()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(producir("-f" in sys.argv))
