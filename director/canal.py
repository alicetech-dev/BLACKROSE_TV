"""Chat del canal (modo stream): lee el chat en vivo y le pasa cada mensaje a la consola, que decide cuál contestan.

Sin claves ni cuentas: Twitch por IRC anónimo, YouTube y Kick por la misma API interna que usa su página de chat.
Solo LEE. Configuración en dolls.sfw.yaml → `canal:`.

  .venv/bin/python -m director.canal twitch <canal>        # probar: imprime lo que llega
  .venv/bin/python -m director.canal youtube <canal|video>
  .venv/bin/python -m director.canal kick <canal>
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sys

import httpx
from websockets.asyncio.client import connect

log = logging.getLogger("director.canal")
MAX_TEXTO = 300
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_YT_HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9", "Cookie": "SOCS=CAI; CONSENT=YES+1"}
_YT_CLIENT = "2.20241212.01.00"


def limpiar(texto: str) -> str:
    """Lo que llega al LLM y a la pantalla: sin links (nunca se abren ni se leen), una línea, largo acotado."""
    texto = _URL.sub("[link]", texto or "")
    return re.sub(r"\s+", " ", texto).strip()[:MAX_TEXTO]


def usuario(plataforma: str, autor: str) -> dict:
    """Identidad del espectador para el agente: id estable y sin caracteres raros (va a nombres de nota y metadatos)."""
    nombre = re.sub(r"[\[\]\n\r]", "", autor or "").strip().lstrip("@")[:40] or "alguien"
    plataforma = re.sub(r"[^\w-]", "", plataforma or "")[:12] or "chat"
    return {"id": f"{plataforma}:{re.sub(r'[^\w-]', '_', nombre.lower())}", "nombre": nombre}


# --- Twitch (IRC anónimo por WebSocket) ---------------------------------------------------
def parse_irc(linea: str) -> tuple[str, str] | None:
    """'@tags :nick!nick@nick.tmi.twitch.tv PRIVMSG #canal :texto' -> (autor, texto). Otra cosa: None."""
    tags = {}
    if linea.startswith("@"):
        crudo, _, linea = linea[1:].partition(" ")
        tags = dict(t.partition("=")[::2] for t in crudo.split(";"))
    m = re.match(r":([^!\s]+)!\S+ PRIVMSG #\S+ :(.*)", linea)
    if not m:
        return None
    return tags.get("display-name") or m.group(1), m.group(2)


async def twitch(canal: str, al_mensaje) -> None:
    canal = canal.strip().lstrip("#@").lower()
    while True:
        try:
            async with connect("wss://irc-ws.chat.twitch.tv:443", open_timeout=10) as ws:
                await ws.send("CAP REQ :twitch.tv/tags")
                await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
                await ws.send(f"JOIN #{canal}")
                log.info("Twitch: leyendo #%s", canal)
                async for crudo in ws:
                    for linea in str(crudo).split("\r\n"):
                        if linea.startswith("PING"):
                            await ws.send("PONG" + linea[4:])
                        elif (r := parse_irc(linea)):
                            al_mensaje(r[0], r[1], "twitch")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001  (se reconecta sola)
            log.warning("Twitch #%s: %s; reintento en 10 s", canal, e)
        await asyncio.sleep(10)


# --- YouTube (API interna del chat en vivo) --------------------------------------------------
def yt_destino(destino: str) -> tuple[str, str]:
    """('video', id) o ('canal', ruta para .../live): acepta id de video, URL, id de canal (UC...) o @handle."""
    d = destino.strip()
    m = re.search(r"(?:v=|youtu\.be/|/live/)([\w-]{11})", d)
    if m:
        return "video", m.group(1)
    m = re.search(r"(UC[\w-]{22})", d)
    if m:
        return "canal", f"channel/{m.group(1)}"
    m = re.search(r"@[\w.-]+", d)
    if m:
        return "canal", m.group(0)
    if re.fullmatch(r"[\w-]{11}", d):
        return "video", d
    return "canal", "@" + d.strip("/ ")


def yt_mensajes(data: dict) -> tuple[list[tuple[str, str, str]], str | None, float]:
    """Respuesta de get_live_chat -> ([(id, autor, texto)], siguiente continuación, segundos hasta el próximo pedido)."""
    lcc = data.get("continuationContents", {}).get("liveChatContinuation", {})
    out = []
    for accion in lcc.get("actions", []):
        item = accion.get("addChatItemAction", {}).get("item", {})
        r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not r:
            continue
        texto = "".join(x.get("text", "") for x in r.get("message", {}).get("runs", []))
        if texto.strip():
            out.append((r.get("id", ""), r.get("authorName", {}).get("simpleText", "?"), texto))
    sig, espera = None, 4.0
    for c in lcc.get("continuations", []):
        for clave in ("invalidationContinuationData", "timedContinuationData", "reloadContinuationData"):
            if c.get(clave, {}).get("continuation"):
                sig = c[clave]["continuation"]
                espera = min(6.0, max(2.0, c[clave].get("timeoutMs", 4000) / 1000))
                break
        if sig:
            break
    return out, sig, espera


async def _yt_video_en_vivo(http: httpx.AsyncClient, ruta: str) -> str | None:
    r = await http.get(f"https://www.youtube.com/{ruta}/live", follow_redirects=True)
    m = (re.search(r"[?&]v=([\w-]{11})", str(r.url))
         or re.search(r'rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', r.text))
    return m.group(1) if m else None


async def _yt_leer(http: httpx.AsyncClient, video: str, al_mensaje) -> None:
    """Lee el chat de un video hasta que se corta (terminó el vivo). Lo que ya estaba escrito al entrar no se pasa."""
    r = await http.get(f"https://www.youtube.com/live_chat?v={video}&embed_domain=localhost")
    tokens = re.findall(r'"continuation":"([^"]+)"', r.text)
    if not tokens:
        raise RuntimeError("ese video no tiene chat en vivo")
    cont, vistos, primera = tokens[1] if len(tokens) > 1 else tokens[0], set(), True
    log.info("YouTube: leyendo el chat de %s", video)
    while cont:
        r = await http.post("https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?prettyPrint=false",
                            json={"context": {"client": {"clientName": "WEB", "clientVersion": _YT_CLIENT, "hl": "en"}},
                                  "continuation": cont},
                            headers={"X-YouTube-Client-Name": "1", "X-YouTube-Client-Version": _YT_CLIENT,
                                     "Referer": f"https://www.youtube.com/live_chat?v={video}"})
        r.raise_for_status()
        mensajes, cont, espera = yt_mensajes(r.json())
        for mid, autor, texto in mensajes:
            if mid in vistos:
                continue
            vistos.add(mid)
            if not primera:
                al_mensaje(autor, texto, "youtube")
        if len(vistos) > 5000:
            vistos.clear()
        primera = False
        await asyncio.sleep(espera)


async def youtube(destino: str, al_mensaje) -> None:
    tipo, valor = yt_destino(destino)
    async with httpx.AsyncClient(timeout=15, headers=_YT_HEADERS) as http:
        while True:
            try:
                video = valor if tipo == "video" else await _yt_video_en_vivo(http, valor)
                if video:
                    await _yt_leer(http, video, al_mensaje)
                else:
                    log.info("YouTube: %s no está en vivo todavía", valor)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  (se reintenta sola)
                log.warning("YouTube %s: %s", valor, e)
            await asyncio.sleep(45)


# --- Kick (Pusher público de su página de chat; no es API oficial, puede cambiar sin aviso) -------
_KICK_WS = "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0&flash=false"


def kick_mensaje(crudo: str) -> tuple[str, str] | None:
    """Frame de Pusher -> (autor, texto) si es un mensaje de chat; otra cosa: None."""
    try:
        ev = json.loads(crudo)
        if ev.get("event") != r"App\Events\ChatMessageEvent":
            return None
        d = json.loads(ev["data"])
        return d["sender"]["username"], d["content"]
    except (ValueError, KeyError, TypeError):
        return None


async def kick(canal: str, al_mensaje) -> None:
    slug = canal.strip().lstrip("@/").rsplit("/", 1)[-1].lower()
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": _UA}) as http:
        while True:
            try:
                r = await http.get(f"https://kick.com/api/v2/channels/{slug}")
                r.raise_for_status()
                sala = r.json()["chatroom"]["id"]
                async with connect(_KICK_WS, open_timeout=10) as ws:
                    await ws.send(json.dumps({"event": "pusher:subscribe",
                                              "data": {"auth": "", "channel": f"chatrooms.{sala}.v2"}}))
                    log.info("Kick: leyendo %s", slug)
                    async for crudo in ws:
                        if (r := kick_mensaje(str(crudo))):
                            al_mensaje(r[0], r[1], "kick")
                        elif '"pusher:ping"' in str(crudo):
                            await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  (se reconecta sola)
                log.warning("Kick %s: %s; reintento en 15 s", slug, e)
            await asyncio.sleep(15)


def lanzar(cfg: dict, al_mensaje) -> list[asyncio.Task]:
    """Una tarea por fuente configurada (`twitch:` / `youtube:` / `kick:`). Sin nada configurado: ninguna."""
    tareas = []
    if cfg.get("twitch"):
        tareas.append(asyncio.create_task(twitch(str(cfg["twitch"]), al_mensaje), name="canal-twitch"))
    if cfg.get("youtube"):
        tareas.append(asyncio.create_task(youtube(str(cfg["youtube"]), al_mensaje), name="canal-youtube"))
    if cfg.get("kick"):
        tareas.append(asyncio.create_task(kick(str(cfg["kick"]), al_mensaje), name="canal-kick"))
    return tareas


def _puente(url: str):
    """Cada mensaje, a la consola por POST /api/canal (sirve si su lector interno se trabó: no hay que reiniciarla)."""
    import urllib.request

    def enviar(autor, texto, plataforma):
        print(f"[{plataforma}] {autor}: {limpiar(texto)}", flush=True)
        req = urllib.request.Request(url, json.dumps({"autor": autor, "texto": texto, "plataforma": plataforma}).encode(),
                                     {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except OSError as e:
            log.warning("no pude pasárselo a la consola: %s", e)
    return enviar


if __name__ == "__main__":
    # python -m director.canal youtube @canal                  muestra el chat
    # python -m director.canal youtube @canal --consola        además se lo pasa a la consola (http://127.0.0.1:8780)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = [a for a in sys.argv[1:] if a != "--consola"]
    if len(args) != 2 or args[0] not in ("twitch", "youtube", "kick"):
        sys.exit(__doc__)
    al = (_puente("http://127.0.0.1:8780/api/canal") if "--consola" in sys.argv
          else lambda a, t, p: print(f"[{p}] {usuario(p, a)['id']} | {a}: {limpiar(t)}", flush=True))
    try:
        asyncio.run({"twitch": twitch, "youtube": youtube, "kick": kick}[args[0]](args[1], al))
    except KeyboardInterrupt:
        pass
