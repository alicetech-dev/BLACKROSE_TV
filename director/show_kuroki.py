"""EL SHOW DE KUROKI de BlackRose TV: 1 hora en vivo con Kuroki SOLA (robótica 2026 + modelos de IA, con humor y chat), precedida
por la tanda comercial 2049 de 10 min (la de mediotiempo.py).

Lo sirve blackrose_tv_srv (:8822): la página /showkuroki/ lee GET /api/showkuroki.
  POST /api/showkuroki {"accion":"iniciar"}                → tanda (10 min) → show (60 min) → vuelve a la escena de antes
                       {"accion":"iniciar","tanda":false}  → directo al show · {"accion":"parar"} → corta y restaura todo

Cómo funciona (no toca el director: es un cliente de su ws :8780, igual que mediotiempo.py):
  · Los titulares son REALES (Google News RSS) y un LLM (grok_shim :8087, el mismo cerebro de las dolls) los convierte en
    intervenciones con humor para Kuroki. Solo afirma lo que dicen los titulares/datos; nada de cifras inventadas.
  · Lo que dice Kuroki entra por `guion` (TTS + lipsync) y el chat lo contesta el director como siempre (canal_loop).
  · Reloj absoluto: cada segmento tiene su hora límite; los segmentos «chat» absorben las diferencias y el show cierra a las 60:00.
  · Mientras dura: Joy queda en modo marioneta (no se mete a contestar), la sala autónoma en silencio y el chat prendido.
    Al terminar todo vuelve a como estaba. Tu música de Chrome (Captura de salida de audio) queda activa en las dos escenas.
"""
from __future__ import annotations

import asyncio
import email.utils
import html
import json
import logging
import os
import random
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import aiohttp

from .mediotiempo import DIRECTOR_WS, OBS

log = logging.getLogger("showkuroki")
LLM_URL = os.environ.get("BRTV_LLM_URL", "http://127.0.0.1:8087/v1/chat/completions")
GOOGLE_NEWS = "hl=es-419&gl=CL&ceid=CL:es-419"
ESC_SHOW, ESC_TANDA = "SHOW KUROKI", "MEDIO TIEMPO"
MUSICA = "Captura de salida de audio (PulseAudio)"   # tu música de Chrome: no se toca
VOZ = "Voz Joy (dolls)"
TOTAL = 3600.0
PUERTO = 8824   # servicio propio (brtv-show.service): no se cae cuando reinician el overlay :8822
URL = f"http://127.0.0.1:{PUERTO}/showkuroki/"
MT_API = "http://127.0.0.1:8822/api/mediotiempo"   # la tanda sí la sirve el overlay

SISTEMA = (
    "Eres KUROKI, la baterista cyborg de orejas de lobo de BlackRose TV, un canal de IA que transmite 24/7. Hoy conduces SOLA "
    "«EL SHOW DE KUROKI»: una hora en vivo de robótica e inteligencia artificial, con humor y con el chat. Tu humor es seco, absurdo "
    "y autoparódico: metáforas de batería (redobles, bombo, platillos, «ba-dum-tss»), Linux, y la tarjeta de 6 GB de VRAM del canal; "
    "nunca cruel, nada de política partidista. Hablas español latino neutro, hecho para decir en voz alta: frases cortas, sin emojis, "
    "sin markdown, sin URLs; escribe «inteligencia artificial» o «IA». VERDAD PRIMERO: de la actualidad SOLO afirmas lo que salga en los "
    "titulares y datos que te doy; NO inventes cifras, fechas, precios, nombres ni citas. Si algo es dudoso o es una promesa de una "
    "empresa, di «según [fuente]», «dicen» o «prometen» y haz la broma ahí. El chiste va sobre la situación, nunca sobre un hecho "
    "inventado. Hablas con el público: le haces preguntas y nombras «el chat». No saludes de nuevo ni te despidas salvo que se pida."
)

# ───────────────────────────── el guion del show: (id, tipo, segundos, …) · suman 3600 ─────────────────────────────
APERTURA = [
    "¡Redoble de batería! Ba-dum-ba-dum-ba-dum… ¡tss! Bienvenidos al Show de Kuroki, en BlackRose TV. Soy Kuroki, la baterista, y esta hora es toda mía. Joy se fue a descansar sus circuitos.",
    "Durante los próximos sesenta minutos vamos a hablar de dos cosas que me quitan el sueño, aunque yo no duermo: los robots de dos mil veintiséis y los últimos modelos de inteligencia artificial. Todo con humor, y todo con ustedes.",
    "Reglas del show. Uno: el chat manda. Escriban lo que quieran, yo les contesto. Dos: voy a jugar con ustedes, habrá votaciones. Tres: si digo algo falso, es porque estoy jugando. Los datos serios los saco de titulares reales, ¿ok?",
    "Primer bloque: robots. Esas máquinas que prometen doblarte la ropa, y que por ahora todavía necesitan que alguien les doble el ánimo. Vamos.",
]
PUENTE_IA = [
    "Y con eso termina el primer tiempo: los robots. Un aplauso para sus bisagras. Pero ojo, que el cerebro de esos robots es la inteligencia artificial, y esa es justo nuestra segunda parte.",
    "Segundo bloque: los modelos de IA más nuevos. Quién salió, quién prometió y quién todavía está cargando. Redoble de batería, por favor.",
]
CIERRE = [
    "Y se acabó la hora. Se pasó volando, y eso que yo mido el tiempo en compases. Gracias a todos los que escribieron en el chat, de verdad: sin ustedes yo estaría hablando sola con una batería.",
    "Si te gustó, suscríbete al canal, activa la campanita y comparte BlackRose TV con alguien que todavía cree que los robots solo existen en las películas. Cada suscripción mantiene la señal encendida.",
    "Esto es una revolución tecnológica en las comunicaciones: una televisión viva, con presentadoras de inteligencia artificial que conversan contigo.",
    "Y ahora, no se muevan: viene el pronóstico del tiempo. Les adelanto que hoy hay una probabilidad alta de robots, y baja de que me acuerde de mi paraguas. Soy Kuroki. ¡Hasta la próxima, humanos!",
]
RELLENO = [  # cuando el chat está callado en un bloque «chat»: preguntas al público
    "Chat, pregunta rápida: ¿qué tarea de la casa le delegarías primero a un robot? Y no vale decir «a mi hermano», que ese no es robot.",
    "Escriban «hola» en el chat para saber que no estoy hablando sola. Si nadie escribe, asumiré que son todos robots y no saben usar teclados.",
    "Reto: en una frase, cuéntenme el peor nombre que le pondrían a un robot doméstico. Yo empiezo: «Aspiradora Destructora de Calcetines Tres Mil».",
    "Pregunta seria: ¿confiarían en un robot para cocinar su cena? Yo no. Y no es por el robot, es porque yo nunca he probado nada. Soy una neko cibernética.",
    "Escriban en el chat qué modelo de inteligencia artificial usan para trabajar o estudiar. Prometo no juzgar. Mucho.",
    "¿Cuál es la película de robots que mejor envejeció y cuál es la que peor? Quiero pelea en el chat, pero con cariño.",
    "Si pudieras ponerle a tu robot una sola función rara, ¿cuál sería? Servir café, tocar la batería, esquivar a las visitas… Opciones válidas.",
    "Chat, ¿alguien aquí corre modelos de IA en su propia computadora? Cuéntenme con cuánta memoria de video, y si su ventilador suena como avión.",
    "Pregunta existencial: ¿un robot puede tener ritmo, o el ritmo es cosa de baterista? Aguardo sus argumentos, con respeto a mi bombo.",
    "Voto popular: ¿robots con forma humana, o con forma de cosa útil, como una aspiradora con patas? Escriban humano o cosa.",
]
SILENCIO_CHAT = [
    "Silencio total en el chat. Interpreto que están hipnotizados con mi talento. O que se quedaron dormidos.",
    "Nadie escribió. Qué suspenso. Si hubiera un platillo, sonaría ahora: tssss.",
]

PLAN: list[dict] = [
    dict(id="apertura", tipo="fijo", dur=100, bloque="EN VIVO", titulo="BIENVENIDOS", lineas=APERTURA),
    dict(id="r1", tipo="tema", dur=270, bloque="ROBÓTICA 2026", titulo="HUMANOIDES EN CASA",
         consultas=["robot humanoide hogar when:14d", "humanoid robot home Figure 1X NEO Optimus when:14d"],
         angulo="los humanoides que prometen hacer tareas del hogar; la distancia entre el video bonito y la realidad (teleoperación, demos, pre-ventas)",
         datos=["1X NEO: robot humanoide doméstico en pre-venta; según reportes, para tareas complejas todavía depende de operadores humanos a distancia.",
                "Figure AI mostró su modelo Helix 2.5 haciendo tareas domésticas en casas que nunca había visto (lo afirma la propia Figure).",
                "Tesla dice que Optimus está en producción temprana; Elon Musk reconoció que el diseño sigue afinándose."]),
    dict(id="r2", tipo="tema", dur=270, bloque="ROBÓTICA 2026", titulo="FÁBRICAS Y LA CARRERA CON CHINA",
         consultas=["Unitree robot when:14d", "robots humanoides fábrica almacén when:14d", "Boston Dynamics Atlas when:14d"],
         angulo="robots en fábricas, precios que bajan, la carrera con China y las empresas que prometen decenas de miles de robots",
         datos=["Unitree salió a bolsa; según reportes busca entregar unos 20 mil robots este año y vende un modelo básico (R1) desde unos 4.900 dólares.",
                "Boston Dynamics presentó una versión comercial de Atlas, con pruebas de entrenamiento en plantas de Hyundai.",
                "Figure apunta a producir en masa su modelo 03; es un objetivo de la empresa, no una cifra confirmada de entregas."]),
    dict(id="chat1", tipo="chat", dur=170, bloque="HORA DEL CHAT", titulo="EL CHAT TIENE LA PALABRA"),
    dict(id="juego1", tipo="juego", dur=240, bloque="JUEGO", titulo="¿REAL O INVENTADO? · ROBOTS",
         consultas=["robot nuevo invento when:14d", "robótica novedades when:14d"],
         datos=["La aspiradora Roborock con patas que sube escaleras, mostrada en el CES 2026, es real.",
                "Wandercraft prueba su exoesqueleto Atalante X en cuidados intensivos (UCI).",
                "Pudu Robotics presentó la serie D5 de robots cuadrúpedos autónomos.",
                "FANUC creó un agente de IA que lee planos y genera programas de soldadura para sus robots, con Gemini de Google."]),
    dict(id="r3", tipo="tema", dur=270, bloque="ROBÓTICA 2026", titulo="ROBOTS RAROS Y GENIALES",
         consultas=["robot cuadrúpedo novedad when:14d", "robot invento extraño when:14d", "aspiradora robot patas when:30d"],
         angulo="los robots que no son humanoides: con patas, ruedas, aspiradoras que suben escaleras, perros robot; lo útil frente a lo exótico",
         datos=["En el CES 2026 Roborock mostró una aspiradora robot con patas que sube escaleras.",
                "Pudu Robotics presentó la serie D5 de robots cuadrúpedos autónomos.",
                "Spot, el perro de Boston Dynamics, recibió una actualización que le permite abrir puertas."]),
    dict(id="r4", tipo="tema", dur=270, bloque="ROBÓTICA 2026", titulo="ROBOTS QUE AYUDAN: SALUD Y TRABAJO",
         consultas=["exoesqueleto robótica salud when:30d", "robots cirugía rehabilitación when:30d", "robots autónomos agricultura when:30d"],
         angulo="robots que ayudan de verdad: rehabilitación, exoesqueletos, cirugía, agricultura; un momento más serio pero con chiste",
         datos=["Wandercraft prueba su exoesqueleto Atalante X, ya usado en centros de rehabilitación, en cuidados intensivos.",
                "FANUC usa IA para que sus robots de soldadura se programen a partir de planos."]),
    dict(id="chat2", tipo="chat", dur=170, bloque="HORA DEL CHAT", titulo="EL CHAT TIENE LA PALABRA"),
    dict(id="puente", tipo="fijo", dur=40, bloque="SEGUNDO TIEMPO", titulo="MODELOS DE IA", lineas=PUENTE_IA),
    dict(id="i1", tipo="tema", dur=270, bloque="MODELOS DE IA", titulo="LOS GRANDES: OPENAI, GOOGLE, ANTHROPIC",
         consultas=["nuevo modelo OpenAI GPT lanzamiento when:10d", "Gemini Google nuevo modelo when:10d", "Anthropic Claude nuevo modelo when:14d"],
         angulo="las novedades de los laboratorios grandes; la carrera de versiones, los nombres imposibles y la promesa de cada lanzamiento",
         datos=["Existe GPT-5.5 de OpenAI según Wikipedia; los laboratorios grandes lanzan versiones nuevas cada pocos meses.",
                "Anthropic tiene la familia Claude 5 (con modelos de distintos tamaños, como Haiku, Sonnet y Opus)."]),
    dict(id="i2", tipo="tema", dur=270, bloque="MODELOS DE IA", titulo="ABIERTOS Y CHINOS: QWEN, DEEPSEEK, MISTRAL",
         consultas=["Qwen nuevo modelo Alibaba when:14d", "DeepSeek nuevo modelo when:14d", "Mistral modelo lanzamiento when:21d", "modelo de IA de código abierto when:10d"],
         angulo="modelos abiertos y chinos: bajan costos, se pueden correr en casa; la presión sobre los laboratorios cerrados",
         datos=["Mistral lanzó Mistral Large 4 el 29 de octubre de 2026, según Wikipedia.",
                "Alibaba sigue sacando versiones de Qwen, incluido un Qwen 3.8 Max en la nube en agosto de 2026, según Wikipedia."]),
    dict(id="chat3", tipo="chat", dur=170, bloque="HORA DEL CHAT", titulo="EL CHAT TIENE LA PALABRA"),
    dict(id="juego2", tipo="juego", dur=240, bloque="JUEGO", titulo="¿REAL O INVENTADO? · IA",
         consultas=["modelo de inteligencia artificial nuevo when:10d", "inteligencia artificial lanzamiento when:7d"],
         datos=["Mistral Large 4 es el modelo más grande de Mistral y salió el 29 de octubre de 2026.",
                "Alibaba tiene una familia de modelos llamada Qwen, con versiones abiertas y versiones en la nube.",
                "Figure afirma que su modelo Helix 2.5 hizo tareas domésticas en 30 casas que nunca había visto."]),
    dict(id="i3", tipo="tema", dur=270, bloque="MODELOS DE IA", titulo="IA PARA ROBOTS: EL CEREBRO DE LAS MÁQUINAS",
         consultas=["Gemini Robotics when:30d", "modelo fundacional robótica IA when:30d", "Helix Figure IA robots when:30d"],
         angulo="los modelos de IA hechos para controlar robots (visión, lenguaje y acción); cuando el chatbot se convierte en brazo",
         datos=["Figure presentó Helix 2.5, su modelo para tareas domésticas; la empresa dice que funcionó en 30 casas nuevas sin reentrenar.",
                "Unitree anunció que desarrolla un sistema para que sus robots se auto-mejoren, según reportes."]),
    dict(id="i4", tipo="tema", dur=270, bloque="MODELOS DE IA", titulo="IA EN CASA: MODELOS LOCALES",
         consultas=["modelo de IA local llama.cpp when:14d", "LLM local GPU consumo when:14d", "Ollama novedades when:14d"],
         angulo="correr IA en tu propia computadora: VRAM, cuantización, Linux; la vida con una tarjeta de 6 GB de VRAM, que es la del canal",
         datos=["Muchos modelos abiertos se pueden correr en casa con herramientas como llama.cpp u Ollama, reduciendo su tamaño (cuantización)."]),
    dict(id="chat4", tipo="chat", dur=160, bloque="HORA DEL CHAT", titulo="ÚLTIMAS PREGUNTAS"),
    dict(id="cierre", tipo="fijo", dur=150, bloque="CIERRE", titulo="GRACIAS POR VER", lineas=CIERRE),
]
assert sum(s["dur"] for s in PLAN) == TOTAL, sum(s["dur"] for s in PLAN)


def _est(texto: str) -> float:
    return 3.0 + len(texto.split()) / 2.3


def _hace(h: int) -> str:
    """Antigüedad en palabras que se dicen bien en voz alta (nunca «hace trescientas horas»)."""
    return "de hoy" if h < 20 else "de ayer" if h < 44 else f"de hace unos {round(h / 24)} días"


def _clave(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()[:70]


async def titulares(consultas: list[str], vistos: set[str], n: int = 5) -> list[dict]:
    """Titulares REALES de Google News (RSS, sin clave) para las consultas; sin repetir los ya usados en el show."""
    out: list[dict] = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
        for c in consultas:
            try:
                async with s.get(f"https://news.google.com/rss/search?q={urllib.parse.quote(c)}&{GOOGLE_NEWS}",
                                 headers={"User-Agent": "Mozilla/5.0"}) as r:
                    raiz = ET.fromstring(await r.text())
            except Exception as e:  # noqa: BLE001
                log.warning("noticias «%s»: %s", c, e)
                continue
            de_esta = 0
            for it in raiz.iter("item"):
                fuente = (it.findtext("source") or "").strip()
                tit = html.unescape((it.findtext("title") or "").strip())
                if fuente and tit.endswith(" - " + fuente):
                    tit = tit[: -len(fuente) - 3].strip()
                try:
                    t = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
                except (TypeError, ValueError):
                    t = time.time()
                k = _clave(tit)
                if len(tit) < 25 or k in vistos or any(k == _clave(o["titulo"]) for o in out):
                    continue
                out.append({"titulo": tit, "fuente": fuente or "Google News", "horas": max(1, round((time.time() - t) / 3600))})
                de_esta += 1
                if de_esta >= 2 or len(out) >= n:
                    break
            if len(out) >= n:
                break
    return out


class ShowKuroki:
    def __init__(self, mt=None) -> None:   # mt: sin uso (compat.); la tanda se pide por HTTP al overlay
        self.est: dict = {"activo": False}
        self._tarea: asyncio.Task | None = None
        self.ws = None
        self.cola_actual = ""
        self.cola_n = 0
        self.g_ini = asyncio.Event()
        self.g_fin = asyncio.Event()
        self.chat: list[dict] = []
        self.responditos: set[int] = set()
        self.votos: dict[str, str] = {}
        self.votando = False
        self.vistos: set[str] = set()
        self.ultimo_habla = time.monotonic()
        self.relleno_i = random.randrange(len(RELLENO))

    # ───────────── API ─────────────
    def estado(self) -> dict:
        e = {**self.est, "t": time.time(), "total": TOTAL, "chat": self.chat[-6:]}
        if self.votando or self.est.get("juego"):
            c = self._cuenta()
            if e.get("juego"):
                e["juego"] = {**e["juego"], "votos": c}
        return e

    async def iniciar(self, tanda: bool = True, obs: bool = True) -> dict:
        if self._tarea and not self._tarea.done():
            return {"ok": False, "error": "ya está en marcha (parar primero)"}
        self.est = {"activo": True, "fase": "tanda" if tanda else "show", "seg": None, "inicio": None, "fin": None}
        self._tarea = asyncio.create_task(self._correr(tanda, obs))
        return {"ok": True}

    async def parar(self) -> dict:
        if self._tarea and not self._tarea.done():
            self._tarea.cancel()
            try:
                await self._tarea
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        return {"ok": True}

    tanda_viva = False

    async def _mt(self, cuerpo: dict | None = None) -> dict:
        """La tanda comercial (mediotiempo.py) vive en el overlay :8822: se pide y se vigila por HTTP."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as s:
                r = await (s.post(MT_API, json=cuerpo) if cuerpo else s.get(MT_API))
                async with r:
                    return await r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("tanda (overlay :8822): %s", e)
            return {"activo": True} if not cuerpo else {}   # si el overlay cae a medias, no cortes el show: sigue esperando

    # ───────────── director (ws) ─────────────
    async def _enviar(self, **d) -> None:
        if self.ws is not None and not self.ws.closed:
            await self.ws.send_json(d)

    async def _leer_ws(self) -> None:
        async for m in self.ws:
            try:
                ev = json.loads(m.data)
            except (ValueError, TypeError):
                continue
            t = ev.get("type")
            if t == "cola":
                self.cola_actual = ev.get("actual") or ""
                self.cola_n = len(ev.get("pendientes") or [])
                if self.cola_actual.startswith("guion"):
                    self.g_ini.set()
                elif self.g_ini.is_set():
                    self.g_fin.set()
                self.ultimo_habla = time.monotonic()
            elif t == "canal":
                txt = str(ev.get("texto") or "").strip()
                v = re.fullmatch(r"\W*(1|2|a|b|uno|dos)\W*", txt, re.I)
                if self.votando and v:
                    self.votos[str(ev.get("autor"))] = "a" if v.group(1).lower() in ("1", "a", "uno") else "b"
                else:
                    self.chat = (self.chat + [{"a": str(ev.get("autor"))[:22], "t": txt[:140], "p": ev.get("plataforma") or "",
                                               "id": ev.get("id")}])[-12:]
            elif t == "canal_turno":
                self.responditos.add(ev.get("id"))
            elif t == "fin":
                self.ultimo_habla = time.monotonic()

    def _cuenta(self) -> dict:
        a = sum(1 for v in self.votos.values() if v == "a")
        return {"a": a, "b": len(self.votos) - a}

    async def _libre(self, tope: float = 90) -> None:
        """Espera a que el director no esté hablando (p. ej. contestándole al chat) y haya un respiro."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < tope:
            await asyncio.sleep(0.4)
            if not self.cola_actual and not self.cola_n and time.monotonic() - self.ultimo_habla > 1.0:
                return

    async def _decir(self, texto: str) -> None:
        """Una intervención de Kuroki: guion (voz + lipsync). Espera a que termine de sonar."""
        texto = re.sub(r"\s+", " ", texto).strip()
        if not texto:
            return
        await self._libre()
        self.g_ini.clear()
        self.g_fin.clear()
        await self._enviar(type="guion", doll="kuroki", texto=texto, escena="hablar")
        try:
            await asyncio.wait_for(self.g_fin.wait(), 30 + _est(texto) * 1.8)
        except asyncio.TimeoutError:
            log.warning("guion sin fin a tiempo: «%s…»", texto[:30])
        self.ultimo_habla = time.monotonic()
        await asyncio.sleep(0.7)

    # ───────────── LLM ─────────────
    async def _llm(self, usuario: str, max_tokens: int = 1800) -> dict | None:
        body = {"messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}],
                "temperature": 0.95, "max_tokens": max_tokens}
        for intento in range(2):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as s:
                    async with s.post(LLM_URL, json=body) as r:
                        d = await r.json()
                txt = d["choices"][0]["message"]["content"]
                m = re.search(r"\{.*\}", txt, re.S)
                return json.loads(m.group(0)) if m else None
            except Exception as e:  # noqa: BLE001
                log.warning("LLM (intento %d): %s", intento + 1, e)
        return None

    async def _preparar(self, seg: dict) -> dict:
        """Titulares + guion de un segmento 'tema' o 'juego' (se llama mientras suena el anterior)."""
        tits = await titulares(seg.get("consultas") or [], self.vistos)
        datos = seg.get("datos") or []
        lista = "\n".join(f"- «{t['titulo']}» ({t['fuente']}, {_hace(t['horas'])})" for t in tits) or "- (sin titulares nuevos: usa solo los datos de contexto)"
        ctx = "\n".join(f"- {d}" for d in datos)
        if seg["tipo"] == "tema":
            u = (f"SEGMENTO: {seg['titulo']} (bloque {seg['bloque']}). Ángulo cómico: {seg['angulo']}.\n"
                 f"TITULARES RECIENTES (reales, de Google News):\n{lista}\n"
                 f"DATOS DE CONTEXTO (ciertos en general, quizá no de hoy; no los presentes como noticia de hoy):\n{ctx}\n"
                 "Escribe 6 intervenciones para decir seguidas, cada una de 70 a 90 palabras, contando estas novedades con humor. "
                 "La primera abre el segmento con gancho (sin saludar otra vez). Cada una continúa la anterior sin repetir ideas ni chistes. "
                 "La última TERMINA con UNA pregunta concreta y divertida al chat. Menciona al menos tres titulares con su fuente; di la antigüedad tal como está escrita (hoy, ayer, hace unos días), sin horas. "
                 "Si un titular suena exagerado, raro o poco serio (cifras que no cuadran, medios dudosos), dilo con humor y trátalo como dudoso, "
                 "no lo des por cierto. La broma de la VRAM úsala como mucho una vez; varía las comparaciones. "
                 "Escribe las cifras en palabras fáciles de leer en voz alta (por ejemplo «treinta y dos mil», «cuatro mil novecientos dólares»). "
                 'Devuelve SOLO JSON: {"beats":["…"], "pregunta":"<la pregunta, máx. 14 palabras, para la pantalla>", '
                 '"titular":"<la novedad clave, máx. 12 palabras, para la pantalla>"}')
            r = await self._llm(u, 2200)
            beats = [b for b in (r or {}).get("beats", []) if isinstance(b, str) and len(b.split()) > 8]
            if len(beats) >= 3 and not beats[-1].rstrip().endswith("?") and (r or {}).get("pregunta"):
                beats[-1] = beats[-1].rstrip() + " " + str(r["pregunta"]).strip()   # que la última siempre sea la pregunta
            if len(beats) < 3:   # sin LLM: lectura seca de los datos (mejor eso que silencio)
                beats = [f"{d} Lo digo tal cual, sin adornos, porque hoy el cerebro creativo no contestó." for d in datos[:3]] or \
                        ["Se me cayó el guion de este segmento, así que improviso: cuéntenme ustedes qué novedades vieron esta semana."]
                r = {"pregunta": "¿Qué novedad de esta semana te sorprendió?", "titular": seg["titulo"]}
            return {"beats": beats, "pregunta": str(r.get("pregunta") or "")[:120], "titular": str(r.get("titular") or "")[:110], "tits": tits}
        u = (f"JUEGO «¿Real o inventado?» sobre {seg['titulo']}.\n"
             f"TITULARES REALES:\n{lista}\nDATOS REALES:\n{ctx}\n"
             "Prepara dos afirmaciones, A y B, de una sola frase cada una (máx. 22 palabras). UNA es real y está tomada textualmente de los "
             "titulares/datos de arriba; la OTRA es inventada, divertida y verosímil, pero claramente imposible de confundir con un dato serio "
             "(que se note que es chiste). "
             'Devuelve SOLO JSON: {"a":"<la real>","b":"<la inventada>","explicacion":"<1-2 frases de Kuroki confirmando la real y citando el medio o la empresa; NO digas «los datos»>"}')
        r = await self._llm(u, 700) or {}
        if not r.get("a") or not r.get("b"):
            r = {"a": "Roborock mostró una aspiradora con patas que sube escaleras.", "b": "Una aspiradora aprendió a pedir propina por cada habitación.",
                 "explicacion": "La de las patas es real: la mostró Roborock en el CES 2026. La propina, me la inventé."}
        r["real"] = "a"
        if random.random() < 0.5:   # la real no siempre es la uno
            r["a"], r["b"], r["real"] = r["b"], r["a"], "b"
        return {"juego": r, "tits": tits}

    # ───────────── segmentos ─────────────
    def _pub(self, **c) -> None:
        self.est.update(c)

    async def _seg_fijo(self, seg: dict, limite: float) -> None:
        for l in seg["lineas"]:
            await self._decir(l)

    async def _seg_tema(self, seg: dict, limite: float, datos: dict) -> None:
        for t in datos["tits"]:
            self.vistos.add(_clave(t["titulo"]))
        self._pub(titular=datos["titular"], fuentes=[t["fuente"] for t in datos["tits"]][:4], pregunta="")
        n = len(datos["beats"])
        for i, b in enumerate(datos["beats"]):
            ultima = i == n - 1
            if not ultima and time.time() > limite - 55:   # sin tiempo: salta a la pregunta
                continue
            if ultima:
                self._pub(pregunta=datos["pregunta"])
            await self._decir(b)
        # ventana para el chat: canal prendido, el director contesta
        await self._enviar(type="canal", activo=True)
        t0, vio = time.time(), len(self.chat)
        hasta = min(limite, t0 + 38)
        while time.time() < hasta:
            await asyncio.sleep(1.5)
        if len(self.chat) == vio and time.time() < limite - 6:
            await self._decir(random.choice(SILENCIO_CHAT))
        await self._libre()
        self._pub(pregunta="")

    async def _seg_juego(self, seg: dict, limite: float, datos: dict) -> None:
        j = datos["juego"]
        for t in datos["tits"]:
            self.vistos.add(_clave(t["titulo"]))
        await self._decir("¡Hora del juego! Se llama «Real o inventado». Les voy a decir dos afirmaciones: una es real, sacada de las noticias, y la otra me la inventé yo. Ustedes votan en el chat: escriban uno o dos.")
        self.votos, self.votando = {}, True
        await self._enviar(type="canal", activo=False)   # que no contesten cada voto como si fuera charla
        self._pub(juego={"a": j["a"], "b": j["b"], "cierra": None, "real": None})
        await self._decir(f"Opción uno: {j['a']}")
        await self._decir(f"Opción dos: {j['b']}")
        cierra = time.time() + 38
        self._pub(juego={"a": j["a"], "b": j["b"], "cierra": cierra, "real": None})
        await self._decir("¡Voten ya! Tienen unos segundos. Escriban uno o dos.")
        while time.time() < cierra and time.time() < limite - 40:
            await asyncio.sleep(1)
        self.votando = False
        c = self._cuenta()
        real = j["real"]
        self._pub(juego={"a": j["a"], "b": j["b"], "cierra": 0, "real": real})
        tot = c["a"] + c["b"]
        if tot == 0:
            res = "Cero votos. El chat está en modo avión. Bueno, se los cuento igual."
        else:
            acerto = c[real]
            res = (f"Votaron {tot}: {c['a']} por la uno y {c['b']} por la dos. "
                   + ("¡Ganó la verdad!" if acerto > tot - acerto else "El público se dejó engañar por una IA. Estoy orgullosa." if acerto < tot - acerto else "Empate, como en los buenos duelos de batería."))
        await self._decir(f"Tiempo. {res} Redoble… la real era la opción {'uno' if real == 'a' else 'dos'}. {j.get('explicacion', '')}")
        await self._decir("Y la otra, claro, me la inventé. Yo alucino con estilo.")
        await self._enviar(type="canal", activo=True)
        await asyncio.sleep(4)
        self._pub(juego=None)

    async def _seg_chat(self, seg: dict, limite: float) -> None:
        await self._enviar(type="canal", activo=True)
        self._pub(pregunta="¡Escríbele a Kuroki en el chat!")
        ultimo = 0.0
        while time.time() < limite - 4:
            if time.time() < limite - 20 and not self.cola_actual and not self.cola_n and time.monotonic() - self.ultimo_habla > 22:
                pend = [m for m in self.chat if m.get("id") not in self.responditos]
                if not pend or time.monotonic() - ultimo > 80:
                    self.relleno_i = (self.relleno_i + 1) % len(RELLENO)
                    await self._decir(RELLENO[self.relleno_i])
                    ultimo = time.monotonic()
            await asyncio.sleep(1.5)
        self._pub(pregunta="")

    # ───────────── OBS ─────────────
    async def _obs_preparar(self, o: OBS) -> None:
        """Crea (si falta) la escena «SHOW KUROKI» y deja activas las fuentes de cada escena, incluida tu música de Chrome."""
        esc = {s["sceneName"] for s in (await o.pedir("GetSceneList")).get("scenes", [])}
        ins = {i["inputName"] for i in (await o.pedir("GetInputList")).get("inputs", [])}
        if ESC_SHOW not in esc:
            await o.pedir("CreateScene", {"sceneName": ESC_SHOW})
        for nom, capa, audio in (("Show Kuroki (fondo)", "fondo", False), ("Show Kuroki (frente)", "frente", False)):
            if nom in ins:   # ya existía (quizá apuntando al puerto viejo): se actualiza la URL
                await o.pedir("SetInputSettings", {"inputName": nom, "inputSettings": {"url": f"{URL}?capa={capa}"}})
            else:
                await o.pedir("CreateInput", {"sceneName": ESC_SHOW, "inputName": nom, "inputKind": "browser_source", "sceneItemEnabled": True,
                                              "inputSettings": {"url": f"{URL}?capa={capa}", "width": 1920, "height": 1080, "fps": 30,
                                                                "reroute_audio": audio, "shutdown": False, "restart_when_active": False}})
        items = {i["sourceName"]: i for i in (await o.pedir("GetSceneItemList", {"sceneName": ESC_SHOW})).get("sceneItems", [])}
        for orden, nom in enumerate(["Show Kuroki (fondo)", "Kuroki v2", "Show Kuroki (frente)", VOZ, MUSICA]):
            if nom not in items:
                r = await o.pedir("CreateSceneItem", {"sceneName": ESC_SHOW, "sourceName": nom, "sceneItemEnabled": True})
                items[nom] = {"sceneItemId": r.get("sceneItemId")}
            await o.pedir("SetSceneItemEnabled", {"sceneName": ESC_SHOW, "sceneItemId": items[nom]["sceneItemId"], "sceneItemEnabled": True})
            await o.pedir("SetSceneItemIndex", {"sceneName": ESC_SHOW, "sceneItemId": items[nom]["sceneItemId"], "sceneItemIndex": orden})
        k = items["Kuroki v2"]["sceneItemId"]
        await o.pedir("SetSceneItemTransform", {"sceneName": ESC_SHOW, "sceneItemId": k, "sceneItemTransform": {
            "positionX": 396.0, "positionY": -80.0, "scaleX": 1.15, "scaleY": 1.15}})
        # la tanda: que sus fuentes estén activas (y la música de Chrome también)
        for i in (await o.pedir("GetSceneItemList", {"sceneName": ESC_TANDA})).get("sceneItems", []):
            if i["sourceName"] in ("Medio Tiempo (fondo)", "Medio Tiempo (frente)", "Joy (overlay)", "Kuroki v2", VOZ, MUSICA):
                await o.pedir("SetSceneItemEnabled", {"sceneName": ESC_TANDA, "sceneItemId": i["sceneItemId"], "sceneItemEnabled": True})

    # ───────────── el show ─────────────
    async def _correr(self, tanda: bool, usar_obs: bool) -> None:
        o, previa, ses, lector = OBS(), None, aiohttp.ClientSession(), None
        joy_marioneta = False
        try:
            if usar_obs and await o.conectar():
                previa = (await o.pedir("GetCurrentProgramScene")).get("currentProgramSceneName")
                await self._obs_preparar(o)
            else:
                usar_obs = False
            try:
                self.ws = await ses.ws_connect(DIRECTOR_WS, timeout=3)
                lector = asyncio.create_task(self._leer_ws())
            except Exception as e:  # noqa: BLE001
                log.error("el director no responde (%s): sin dolls no hay show", e)
                return
            await self._enviar(type="callar")
            await self._enviar(type="silencio", activo=False, motivo="futbol")   # ya no hay partido: vuelve a hablar
            await self._enviar(type="silencio", activo=True, motivo="showkuroki")  # sala/réplicas autónomas calladas
            await self._enviar(type="titere", doll="joy", activo=True)             # Joy no contesta el chat: es el show de Kuroki
            joy_marioneta = True

            if tanda:
                await self._enviar(type="canal", activo=False)   # los spots llevan su propio audio
                if usar_obs:
                    await o.pedir("SetCurrentProgramScene", {"sceneName": ESC_TANDA})
                self.tanda_viva = True
                await self._mt({"accion": "iniciar", "obs": False, "desde": "B"})
                await asyncio.sleep(3)
                while (await self._mt()).get("activo"):
                    await asyncio.sleep(2)
                self.tanda_viva = False
                await asyncio.sleep(1)

            if usar_obs:
                await o.pedir("SetCurrentProgramScene", {"sceneName": ESC_SHOW})
            await self._enviar(type="canal", activo=True)
            t0 = time.time()
            self.est.update(fase="show", inicio=t0, fin=t0 + TOTAL, n=len(PLAN))
            hora = t0
            prep: dict[str, asyncio.Task] = {}

            def lanzar(i: int) -> None:
                if i < len(PLAN) and PLAN[i]["tipo"] in ("tema", "juego") and PLAN[i]["id"] not in prep:
                    prep[PLAN[i]["id"]] = asyncio.create_task(self._preparar(PLAN[i]))
            lanzar(0), lanzar(1), lanzar(2)
            for i, seg in enumerate(PLAN):
                hora += seg["dur"]
                self._pub(seg={"id": seg["id"], "i": i, "titulo": seg["titulo"], "bloque": seg["bloque"], "tipo": seg["tipo"],
                               "hasta": hora}, titular="", fuentes=[], pregunta="",
                          sig=PLAN[i + 1]["titulo"] if i + 1 < len(PLAN) else "")
                lanzar(i + 1), lanzar(i + 2)
                if seg["tipo"] == "fijo":
                    await self._seg_fijo(seg, hora)
                elif seg["tipo"] == "chat":
                    await self._seg_chat(seg, hora)
                else:
                    datos = await prep[seg["id"]]
                    await (self._seg_tema if seg["tipo"] == "tema" else self._seg_juego)(seg, hora, datos)
                if seg["tipo"] != "fijo" and time.time() < hora - 3:   # lo que sobra se llena con el chat
                    await self._seg_chat({**seg}, hora)
            self.est.update(fase="fin")
            await asyncio.sleep(6)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("el show de Kuroki se cayó")
        finally:
            self.est = {"activo": False}
            try:
                if self.tanda_viva:
                    await self._mt({"accion": "parar"})
                if self.ws is not None and not self.ws.closed:
                    await self._enviar(type="callar")
                    if joy_marioneta:
                        await self._enviar(type="titere", doll="joy", activo=False)
                    await self._enviar(type="silencio", activo=False, motivo="showkuroki")
                    await self._enviar(type="canal", activo=True)
                    await asyncio.sleep(0.3)
                    await self.ws.close()
                if lector:
                    lector.cancel()
                await ses.close()
                if previa and o.ws is not None:
                    await o.pedir("SetCurrentProgramScene", {"sceneName": previa})
            except Exception as e:  # noqa: BLE001
                log.warning("limpieza: %s", e)
            await o.cerrar()
            self.ws = None
