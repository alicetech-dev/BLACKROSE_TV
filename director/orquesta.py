"""ORQUESTA de BlackRose: el vigilante failsafe. Cada 30 s revisa cada pieza y relanza la que se cayó; nunca apaga el stream.

  PC (RTX)     llm4b :8089 · cerebro :8087 · dolls (agente :8791, director :8780, overlays :8810/:8811, escenario :8812)
               tv-noche · tv-productor · brtv-pensador · japon-capa · brtv-overlay :8822 · relé :1935 · OBS (transmitiendo)
  ThinkPad     llm9b :8095 (9B por CPU) por ssh
  Reglas:
   · JUEGO en la RTX (proceso de steamapps/common) o ventana de Fast Penguin (anclas con "especial") → se APAGA el 4B
     para dejarle la GPU al juego (lección del 18-nov: VRAM llena + Steam = RTX trabada); el cerebro pasa todo al 9B
     del ThinkPad. Al terminar, vuelve el 4B.
   · director de las dolls reiniciado → se le mandan de nuevo los silencios de la TV (si no, vuelve la charla suelta cada 20 s).
   · estado de la TV sin moverse > 25 min (fuera de pausa/externo/Fast Penguin) → se reinicia tv-noche.
   · OBS abierto pero sin transmitir → StartStream. OBS cerrado → se abre (sin variables NVIDIA) transmitiendo.
  Estado: logs/salud.json · log: logs/orquesta.log · servicio: brtv-orquesta.service
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import subprocess
import time

import aiohttp

log = logging.getLogger("orquesta")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(RAIZ, "logs")
TP = "alice@192.168.1.6"
SERVICIOS = ["cerebro", "tv-noche", "tv-productor", "brtv-pensador", "japon-capa", "brtv-overlay", "sala3d", "brtv-chat"]
PAUSA_CANAL = os.path.join(LOGS, "pausa_canal")   # la consola pausó el canal: no se relanza tv-noche
ENVIVO = os.path.join(LOGS, "envivo")      # lo crea `tv.sh envivo on`: Alice transmite ella → no se levanta el director de TV ni se tocan escenas
NIVELES = {0: "todo arriba", 1: "sin 4B: piensa el 9B del ThinkPad", 2: "sin LLM: plantillas, reglas y caché",
           3: "sin red de entrada: archivo, reposiciones y música local", 4: "OBS o relé caído: relanzando"}
DOLLS = {8791: "agente", 8780: "director", 8810: "overlay", 8811: "overlay_kuroki", 8812: "escenario", 8770: "joy_vmc_joy", 8771: "joy_vmc_kuroki"}
OBS_CMD = ["flatpak", "run", "com.obsproject.Studio", "--collection", "Joy Discord", "--scene", "TV NOCHE", "--startstreaming", "--disable-shutdown-check"]


def sh(*cmd, timeout=60, env=None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def activo(svc: str) -> bool:
    return sh("systemctl", "--user", "is-active", svc)[1] == "active"


def escucha(puerto: int) -> bool:
    return f":{puerto} " in sh("ss", "-ltn")[1]


async def get(url: str, t: float = 3) -> int:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=t)) as s, s.get(url) as r:
            return r.status
    except Exception:  # noqa: BLE001
        return 0


def juego_en_rtx() -> str | None:
    _, out = sh("pgrep", "-af", "steamapps/common")
    for l in out.splitlines():
        if "pgrep" not in l and any(x in l.lower() for x in (".exe", "/game", "faaast", "penguin")):
            return l.split(None, 1)[-1][:80]
    return None


def ventana_especial() -> bool:
    """¿Estamos en un ancla «especial» (Fast Penguin en vivo) o 10 min antes?"""
    try:
        c = json.load(open(os.path.join(RAIZ, "director", "tv", "cartelera.json"), encoding="utf-8"))
        fecha = c.get("jornada")
        base = dt.datetime.strptime(fecha, "%Y-%m-%d").date() if fecha else dt.date.today()
    except (OSError, ValueError):
        return False
    n = dt.datetime.now()
    for b in c.get("bloques", []):
        if b.get("especial"):
            h, m = map(int, b["ini"].split(":"))
            a = dt.datetime.combine(base + dt.timedelta(days=1 if h < 12 else 0), dt.time(h, m))
            if a - dt.timedelta(minutes=10) <= n < a + dt.timedelta(minutes=b.get("dura", 120)):
                return True
    return False


class Orquesta:
    def __init__(self):
        self.relay_rearme = 0.0
        self.llm_muestras: list[tuple[float, int]] = []
        self.fallas: dict[str, int] = {}
        self.salud: dict = {}
        self.gpu_cedida = False

    def nota(self, k: str, ok: bool, detalle: str = "") -> None:
        self.salud[k] = {"ok": ok, "detalle": detalle, "t": time.strftime("%H:%M:%S")}
        self.fallas[k] = 0 if ok else self.fallas.get(k, 0) + 1

    async def obs(self) -> None:
        from director.mediotiempo import OBS
        o = OBS()
        try:
            if not await asyncio.wait_for(o.conectar(), 6):
                raise RuntimeError("sin websocket")
            st = await asyncio.wait_for(o.pedir("GetStreamStatus"), 6)
            if not st.get("outputActive"):
                log.warning("OBS no transmite: StartStream")
                await o.pedir("StartStream")
                self.nota("obs", False, "reanudado")
            else:
                self.nota("obs", True, st.get("outputTimecode", ""))
        except Exception as e:  # noqa: BLE001
            vivo = sh("pgrep", "-x", "obs")[0] == 0
            self.nota("obs", False, f"{'abierto sin ws' if vivo else 'cerrado'}: {e}")
            if not vivo and self.fallas["obs"] >= 2:
                log.warning("OBS cerrado: lo abro transmitiendo")
                env = {k: v for k, v in os.environ.items() if not k.startswith(("__NV", "__GLX", "DRI_PRIME", "__VK"))}
                subprocess.Popen(OBS_CMD, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        finally:
            try:
                await o.cerrar()
            except Exception:  # noqa: BLE001
                pass

    async def calmar_dolls(self) -> None:
        """Silencios de la TV (los guarda el director en memoria: un reinicio los borra)."""
        try:
            async with aiohttp.ClientSession() as s, s.ws_connect("ws://127.0.0.1:8780/ws", timeout=5) as ws:
                for m in ({"type": "sala", "activo": False}, {"type": "canal", "activo": False}, {"type": "silencio", "activo": True, "motivo": "ahorro-tokens"}):
                    await ws.send_json(m)
            log.info("silencios de la TV reenviados al director")
        except Exception as e:  # noqa: BLE001
            log.warning("no pude calmar a las dolls: %s", e)

    async def vuelta(self) -> None:
        # 1) GPU: juego o Fast Penguin → el 4B cede la RTX
        juego = juego_en_rtx()
        from ligero.cerebro import grok_activo
        grok = grok_activo()        # ventana Grok (2 h): piensa la nube y el 4B descansa
        ceder = bool(juego) or ventana_especial() or grok
        if ceder and activo("llm4b"):
            log.warning("cedo la RTX (%s): apago el 4B", juego or ("ventana Grok" if grok else "ventana Fast Penguin"))
            sh("systemctl", "--user", "stop", "llm4b")
            self.gpu_cedida = True
        elif not ceder and not activo("llm4b"):
            log.info("RTX libre: vuelve el 4B")
            sh("systemctl", "--user", "start", "llm4b")
            self.gpu_cedida = False
        self.nota("llm4b", ceder or await get("http://127.0.0.1:8089/health") == 200, ("ventana Grok: piensa la nube" if grok else "cedido al juego") if ceder else "")
        if not ceder and self.fallas.get("llm4b", 0) >= 4:
            log.warning("el 4B no responde hace 2 min: reinicio")
            sh("systemctl", "--user", "restart", "llm4b")
            self.fallas["llm4b"] = 0
        # 2) 9B del ThinkPad
        rc, out = sh("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", TP, "systemctl --user is-active llm9b || systemctl --user start llm9b", timeout=15)
        self.nota("llm9b", await get("http://192.168.1.6:8095/health", 4) == 200, out[:40])
        # 3) servicios de la TV
        envivo = os.path.exists(ENVIVO)
        for svc in SERVICIOS:
            ok = activo(svc)
            if svc == "tv-noche" and (envivo or os.path.exists(PAUSA_CANAL)):
                self.nota(svc, True, "apartado: Alice en vivo" if envivo else "canal en pausa (consola)")
                continue
            self.nota(svc, ok)
            if not ok:
                log.warning("%s caído: lo levanto", svc)
                sh("systemctl", "--user", "start", svc)
        # 4) dolls (joy_discord.sh start es idempotente: solo prende lo que falte)
        caidas = [n for p, n in DOLLS.items() if not escucha(p)]
        self.nota("dolls", not caidas, ",".join(caidas))
        if caidas and self.fallas["dolls"] >= 2:
            log.warning("dolls caídas (%s): joy_discord.sh start", caidas)
            for n in caidas:      # pid viejo de un proceso muerto/colgado → se borra para que lo relance
                pf = os.path.join(LOGS, f"{n}.pid")
                if os.path.exists(pf):
                    try:
                        os.kill(int(open(pf).read()), 15)
                    except (OSError, ValueError):
                        pass
                    os.remove(pf)
            sh(os.path.join(RAIZ, "joy_discord.sh"), "start", timeout=240, env={**os.environ, "JOY_LLM": "externo"})
            if "director" in caidas:
                await asyncio.sleep(3)
                await self.calmar_dolls()
        # 5) relé RTMP
        pf = os.path.join(LOGS, "relay.pid")
        vivo = os.path.exists(pf) and sh("kill", "-0", open(pf).read().strip())[0] == 0
        destinos = self.destinos_relay() if vivo else set()
        faltan = {"twitch", "youtube"} - destinos
        self.nota("relay", vivo and not faltan, ("falta " + ", ".join(sorted(faltan))) if vivo and faltan else ", ".join(sorted(destinos)))
        if vivo and faltan and self.fallas["relay"] >= 5 and time.time() - self.relay_rearme > 1800:
            log.warning("relé sin %s hace 2,5 min: lo rearmo (corte de segundos; OBS se reconecta solo)", faltan)
            self.relay_rearme = time.time()
            try:
                os.kill(int(open(pf).read().strip()), 15)
            except (OSError, ValueError):
                pass
            # el ffmpeg hijo de relay.sh quedaba huérfano con el puerto 1935 tomado (solo a Twitch, 6 h sin YouTube el 2026-11-19)
            for d in os.listdir("/proc"):
                try:
                    cmd = open(f"/proc/{d}/cmdline", "rb").read().replace(b"\0", b" ")
                    if d.isdigit() and cmd.startswith(b"ffmpeg") and b"-listen 1 -i rtmp://127.0.0.1:1935/live/obs" in cmd:
                        os.kill(int(d), 15)
                except (OSError, ValueError):
                    pass
            await asyncio.sleep(3)
            vivo = False
        if not vivo:
            log.warning("relé caído: lo levanto")
            sh(os.path.join(RAIZ, "joy_discord.sh"), "start", timeout=240, env={**os.environ, "JOY_LLM": "externo"})
        # 6) OBS
        await self.obs()
        # 7) ¿la TV se trabó? (con Alice en vivo la TV está apartada a propósito)
        try:
            est = json.load(open(os.path.join(RAIZ, "director", "tv", "estado.json"), encoding="utf-8"))
            h = dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(est["t"]))
            quieto = (dt.datetime.now() - h).total_seconds() % 86400
        except (OSError, ValueError, KeyError):
            est, quieto = {}, 0
        trabado = quieto > 1500 and est.get("fase") in ("bloque",) and not ventana_especial() and not envivo and not os.path.exists(PAUSA_CANAL)
        self.nota("tv_flujo", not trabado, f"{est.get('bloque')} · {est.get('item', '')[:40]} · quieto {quieto:.0f}s")
        if trabado and self.fallas["tv_flujo"] == 1:
            log.warning("la TV no avanza hace %.0f s: reinicio tv-noche", quieto)
            sh("systemctl", "--user", "restart", "tv-noche")
        # 8) nivel de degradación y llamadas al LLM por hora
        await self.nivel(envivo)
        self.salud["_t"] = time.strftime("%Y-%m-%d %H:%M:%S")
        json.dump(self.salud, open(os.path.join(LOGS, "salud.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def destinos_relay(self) -> set[str]:
        """Conexiones salientes del ffmpeg del relé: 443 = YouTube (rtmps), 1935 = Twitch."""
        _, out = sh("ss", "-tnpH", "state", "established")
        d = set()
        for l in out.splitlines():
            if "ffmpeg" in l and "127.0.0.1" not in l.split()[3]:
                d.add("youtube" if l.split()[3].endswith(":443") else "twitch" if l.split()[3].endswith(":1935") else "otro")
        return d

    async def nivel(self, envivo: bool) -> None:
        n, motivos = 0, []
        c = {}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s, s.get("http://127.0.0.1:8087/health") as r:
                c = await r.json()
        except Exception:  # noqa: BLE001
            pass
        b = c.get("backends", {})
        if not b.get("4b"):
            n = max(n, 1); motivos.append("sin 4B")
        if not any(b.values()):
            n = max(n, 2); motivos.append("sin LLM")
        if await get("https://news.google.com/rss?hl=es-419", 6) != 200:
            n = max(n, 3); motivos.append("sin RSS")
        if not self.salud.get("obs", {}).get("ok") or not self.salud.get("relay", {}).get("ok"):
            n = max(n, 4); motivos.append("OBS/relé")
        total = sum(v for k, v in (c.get("pedidos") or {}).items() if k.endswith(":ok"))
        ahora = time.time()
        self.llm_muestras = [(t, x) for t, x in self.llm_muestras if ahora - t < 3700] + [(ahora, total)]
        hora = total - self.llm_muestras[0][1] if total >= self.llm_muestras[0][1] else total
        self.salud["nivel"] = {"n": n, "que": NIVELES[n], "motivos": motivos, "llm_ultima_hora": hora,
                               "minutos_medidos": round((ahora - self.llm_muestras[0][0]) / 60), "envivo": envivo, "t": time.strftime("%H:%M:%S")}
        if n != getattr(self, "_nivel_ant", None):
            log.warning("nivel %d: %s %s", n, NIVELES[n], motivos)
            self._nivel_ant = n

    async def autoexamen(self) -> None:
        """Cada ~5 min mira lo que VE el espectador (escenas vacías = negro, páginas, spots, stock de cortes) y repara; ver director/autoexamen.py."""
        rc, out = await asyncio.to_thread(sh, os.path.join(RAIZ, ".venv/bin/python"), "-m", "director.autoexamen", timeout=360, env={**os.environ, "PYTHONPATH": RAIZ})
        try:
            r = json.loads(out[out.index("{"):])
            self.nota("autoexamen", not r.get("problemas"), "; ".join(r.get("problemas", []))[:120])
            for a in r.get("arreglos", []):
                log.warning("autoexamen reparó: %s", a)
        except ValueError:
            self.nota("autoexamen", False, out[-80:])

    async def demonio(self) -> None:
        log.info("orquesta lista")
        n = 0
        while True:
            n += 1
            if n % 10 == 1 and not os.path.exists(ENVIVO):     # el autoexamen repara fuentes de OBS: no con Alice en vivo
                try:
                    await self.autoexamen()
                except Exception:  # noqa: BLE001
                    log.exception("autoexamen con error; sigo")
            try:
                await self.vuelta()
            except Exception:  # noqa: BLE001
                log.exception("vuelta con error; sigo")
            await asyncio.sleep(30)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(Orquesta().demonio())
