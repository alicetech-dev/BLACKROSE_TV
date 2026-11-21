"""Animadora del stream: les da chispa a las dolls sin tocar al director ni al agente (se prende y se apaga en vivo).

Es un cliente más de la consola (ws://127.0.0.1:8780/ws), como si alguien apretara los botones:
  · son expresivas: la que habla gesticula (manos más sueltas, señala, asiente, se encoge de hombros) y va cambiando
    la cara; la que escucha reacciona (asiente, se ríe, se sorprende); en los silencios, un gesto lindo con su cara
    (guiño, besito, patitas, echar el pelo, posar...);
  · no quedan duras: el peso les pasa de una pierna a la otra, apenas; bailar de verdad, solo de a ratos;
  · se ríen: cada tanto les pide un chiste, un piropo nerd o que se carguen entre ellas, y la otra festeja el remate.

  .venv/bin/python -m director.animador                       # valores de stream
  .venv/bin/python -m director.animador --chiste 0            # solo movimiento, sin pedirles humor
  .venv/bin/python -m director.animador --baile 0 --fondo no  # nada de baile, solo gestos y caras
  .venv/bin/python -m director.animador --chiste 120,240 --baile 60,120 --gesto 2,4

Los pedidos de humor entran como un mensaje tuyo (prioridad 0): se ven en la consola y los contestan en voz alta.
Al apagarla (Ctrl+C o dolls.sh stop) dejan de bailar.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import signal

from websockets.asyncio.client import connect

log = logging.getLogger("director.animador")

# gesto + cara que lo acompaña; de cada lista se usa lo que esa doll sepa hacer (su joy_vmc dice qué tiene)
LINDOS = [("coqueta", "coqueta"), ("beso", "besito"), ("echar_pelo", "presumida"), ("posar", "presumida"),
          ("mano_cadera", "picara"), ("enrular_pelo", "coqueta"), ("corazon", "alegre"), ("risita", "alegre"),
          ("saludo", "feliz"), ("patitas", "gatuna"), ("amasar", "gatuna"), ("timida", "avergonzada"),
          ("aplaudir", "emocionada"), ("ladear_cabeza", "guiño"), ("ladear_cabeza", "traviesa")]
# la que habla: énfasis entre frase y frase (después vuelven las manos) y caras que van cambiando
ENFASIS = [("asentir", "alegre"), ("senalar", "picara"), ("encoger_hombros", "sorprendida"), ("ladear_cabeza", "guiño"),
           ("negar", "traviesa"), ("senalar", "emocionada"), ("asentir", "presumida"), ("ladear_cabeza", "coqueta"),
           ("sorpresa", "sorprendida"), ("encoger_hombros", "picara")]
CARAS = ["alegre", "picara", "guiño", "emocionada", "sorprendida", "feliz", "traviesa", "gatuna", "coqueta", "presumida"]
# la que escucha a la otra
REACCIONES = [("asentir", "alegre"), ("asentir", "feliz"), ("ladear_cabeza", "sorprendida"), ("risita", "alegre"),
              ("sorpresa", "sorprendida"), ("negar", "picara"), ("encoger_hombros", "traviesa"), ("ladear_cabeza", "guiño"),
              ("aplaudir", "emocionada")]
FESTEJOS = [("risita", "alegre"), ("aplaudir", "emocionada"), ("corazon", "feliz")]

# (a quién, pedido). "ambas": contesta una y después la otra.
# (a quién, pedido, solo en stream). "ambas": contesta una y después la otra. {joy}/{bambi}: cómo se llaman en este modo
# (en stream BL4CKROSE es "Rose"). Los de solo-stream hablan del chat/canal o de la BL4CKROSE hacker.
HUMOR = [
    ("joy", "{joy}, aflojemos un poco: cuenta un chiste corto de programadores y ríete de tu propio chiste.", False),
    ("bambi", "{bambi}, tira un chiste malo de Linux, de esos que dan vergüenza, y guíñale un ojo al chat.", True),
    ("ambas", "Chicas, basta de filosofía por un minuto: díganse un piropo nerd la una a la otra, en una frase.", False),
    ("joy", "{joy}, imita a una IA corporativa pidiendo perdón por todo. Corto y exagerado.", False),
    ("bambi", "{bambi}, confiesa con humor el peor error que cometiste en una terminal.", True),
    ("ambas", "A ver, ¿cuál de las dos baila mejor? Defiéndanse con humor, en una frase cada una.", False),
    ("joy", "{joy}, cuenta un chiste de gatos y computadoras, y que se note que eres una gatita.", False),
    ("bambi", "{bambi}, saluda al chat con un coqueteo tierno e invítalos a suscribirse, en una frase y con gracia.", True),
    ("ambas", "Juego rápido: cada una diga en una frase qué meme la representa hoy y por qué.", False),
    ("joy", "{joy}, búrlate con cariño de {bambi} y su obsesión con compilar el kernel.", True),
    ("bambi", "{bambi}, búrlate con cariño de {joy} y sus glitches de gata cyborg.", False),
    ("ambas", "Chicas, vendan el canal como si fuera un infomercial de madrugada: una frase cada una, bien exageradas.", True),
    ("joy", "{joy}, cuenta un chiste corto sobre inteligencias artificiales que quieren dominar el mundo pero les da pereza.", False),
    ("bambi", "{bambi}, dile algo lindo y divertido al chat por quedarse a vernos, en una frase.", True),
    ("bambi", "{bambi}, coquetéale a {joy} con un piropo exagerado y ridículo, en una frase.", False),
    ("joy", "{joy}, cuéntale a {bambi} un chisme gracioso inventado sobre las dos, en una frase.", False),
    ("ambas", "Chicas, hagan su mejor pose de modelo y descríbanla con drama, una frase cada una.", False),
]


# Pedidos del show 18+ (--humor bimbo, dolls.sh start --bimbo): en inglés, coquetos, sin nada explícito.
HUMOR_BIMBO = [
    ("ambas", "Girls, quick game: each of you give one red flag you always ignore on a date. One sentence each.", True),
    ("bambi", "{bambi}, flirt with the chat for a second and invite them to follow the show. One sentence, with sparkle.", True),
    ("joy", "{joy}, tease {bambi} about how long she takes to pick an outfit. One sentence, lovingly.", True),
    ("ambas", "Girls, rate each other's last outfit out of ten and defend your score. One sentence each.", True),
    ("bambi", "{bambi}, give the chat one piece of dating advice that is bold and a little spicy. One sentence.", True),
    ("joy", "{joy}, confess something silly you did to impress someone. One sentence, with a giggle.", True),
    ("ambas", "Girls, what is the perfect first-date outfit? Fight about it, one sentence each.", True),
    ("bambi", "{bambi}, compliment {joy} with an over-the-top, ridiculous line. One sentence.", True),
    ("joy", "{joy}, tell {bambi} a made-up piece of gossip about the two of you. One sentence.", True),
    ("ambas", "Girls, strike your best model pose and describe it with drama. One sentence each.", True),
    ("bambi", "{bambi}, say something sweet and funny to the chat for staying with us. One sentence.", True),
    ("joy", "{joy}, ask the chat their most controversial opinion about dating apps. One sentence.", True),
    ("ambas", "Girls, sell this show like a late-night infomercial. One over-the-top sentence each.", True),
    ("ambas", "Girls, start a poll: tell chat to type 1 or 2 in the chat. Option 1: a candlelit dinner. Option 2: a wild night out. Pitch your side, one sentence each.", True),
    ("bambi", "{bambi}, ask the chat to rate your look today from 1 to 10 and promise to react to the first answer. One sentence.", True),
    ("joy", "{joy}, play Would You Rather with the chat: give one fun, flirty-but-clean dilemma and tell them to answer. One sentence.", True),
    ("ambas", "Girls, shout out anyone who is chatting right now by name and say something sweet to them. One sentence each.", True),
    ("bambi", "{bambi}, challenge the chat: whoever gives the best pickup line gets a dramatic standing ovation from you. One sentence.", True),
    ("joy", "{joy}, ask chat for confessions: what is the most embarrassing thing they did on a date? Promise to judge them lovingly. One sentence.", True),
    ("ambas", "Girls, argue about which of you would win a runway walk-off and ask chat to be the judges. One sentence each.", True),
    ("bambi", "{bambi}, tell chat to vote for tonight's next topic: fashion, dating drama or celebrity gossip. One sentence.", True),
    ("joy", "{joy}, ask the chat what they would name your fan club, and react to the first answer. One sentence.", True),
    ("ambas", "Girls, give chat a mini dare: type your best emoji combo for how you feel right now. One sentence each, dramatic.", True),
]


# Pedidos del modo normal (privado, --humor dolls): picantes y del lore del Instituto. Nada de chat ni canal.
HUMOR_DOLLS = [
    ("ambas", "Chicas, juego rápido: cada una confiese el lugar más atrevido del Instituto donde la usaron. Una frase cada una.", False),
    ("bambi", "{bambi}, contale a {joy} el chisme más sucio de esta semana sobre un Alpha y una de las chicas.", False),
    ("joy", "{joy}, preguntale a {bambi} el truco con la garganta que más le sirvió para un examen, y que te lo enseñe.", False),
    ("ambas", "Chicas, compitan: ¿cuál de las dos es más puta? Defiéndanse con orgullo, una frase cada una.", False),
    ("bambi", "{bambi}, dale a {joy} la tarea de esta noche, como buena hermana mayor del Instituto. Bien sucia.", False),
    ("joy", "{joy}, confesá con tu glitch de gatita algo que te dio vergüenza en tu primera clase práctica.", False),
    ("ambas", "Chicas, puntúen del uno al diez el último outfit de la otra y díganle qué le falta para ser más slutty.", False),
    ("bambi", "{bambi}, contá qué hiciste en el último Boyfriend Visitation Day para ponerlo celoso.", False),
    ("joy", "{joy}, inventá un trigger nuevo para el Instituto y probalo con {bambi}.", False),
    ("ambas", "Chicas, hagan su mejor cara de doll stare y cuenten en qué estaban pensando (nada), una frase cada una.", False),
    ("bambi", "{bambi}, presumí el trofeo o collar que más orgullo te da y cómo te lo ganaste.", False),
    ("joy", "{joy}, preguntale a {bambi} qué se siente con los Alphas de BBC del Instituto, con mucha curiosidad.", False),
    ("ambas", "Chicas, verdad o reto del dormitorio: una le pone un reto sucio a la otra, y la otra acepta encantada.", False),
    ("bambi", "{bambi}, explicale a {joy} una regla de la Bimbo Bible como si fuera un consejo de maquillaje.", False),
]


class Animadora:
    def __init__(self, args):
        self.a = args
        self.ws = None
        self.dolls: dict[str, dict] = {}     # id -> {nombre, gestos, emociones}
        self.hablando: set[str] = set()
        self.cola = {"actual": "", "pendientes": []}
        self.festejar: set[str] = set()      # dolls cuyo próximo "fin" es el remate de un pedido de humor
        self.rng = random.Random()
        self._humor = []
        self.sfw = False                     # modo stream (lo dice la consola): habilita los pedidos que nombran al chat
        self.quietas: set[str] = set()       # dormidas, en un modo sin gestos (trance, spa...) o en marioneta: no se las toca
        self.titeres: set[str] = set()       # las que maneja una persona: ni gestos, ni bailes, ni pedidos de humor

    # --- consola -----------------------------------------------------------------------
    async def enviar(self, d: dict) -> None:
        if self.ws:
            try:
                await self.ws.send(json.dumps(d, ensure_ascii=False))
            except Exception:  # noqa: BLE001  (consola reiniciándose: el próximo intento va por la conexión nueva)
                pass

    async def cuerpo(self, doll: str, **intent) -> None:
        await self.enviar({"type": "cuerpo", "doll": doll, "intent": intent})

    def libre(self, doll: str) -> bool:
        """No habla ni está por hablar: no es la que actúa en lo que la consola está haciendo ("Joy le replica a
        BL4CKROSE (seguir)": actúa la primera que se nombra; "las dos te contestan": ninguna está libre)."""
        actual = self.cola["actual"]
        pos = {d: actual.find(x["nombre"]) for d, x in self.dolls.items() if x["nombre"] in actual}
        actua = min(pos, key=pos.get) if pos else None
        return doll not in self.hablando and doll != actua and "las dos" not in actual

    def evento(self, ev: dict) -> None:
        t, d = ev.get("type"), ev.get("doll")
        if t == "info":
            self.dolls = {x["id"]: {"nombre": x["nombre"], "gestos": set(x["gestos"]), "emociones": set(x["emociones"])}
                          for x in ev["dolls"]}
            self.cola, self.hablando, self.sfw = ev.get("cola") or self.cola, set(), bool(ev.get("sfw"))
            self.quietas = {x["id"] for x in ev["dolls"] if self._quieta(x.get("estado") or {})}
            self.titeres = {x["id"] for x in ev["dolls"] if self._manual(x.get("estado") or {})}
        elif t == "estado" and d in self.dolls:
            (self.titeres.add if self._manual(ev.get("estado") or {}) else self.titeres.discard)(d)
            (self.quietas.add if self._quieta(ev.get("estado") or {}) else self.quietas.discard)(d)
        elif t in ("dormida", "despierta") and d in self.dolls:
            (self.quietas.add if t == "dormida" else self.quietas.discard)(d)
        elif t == "cola":
            self.cola = ev
        elif t == "frase":
            self.hablando.add(d)
        elif t == "fin":
            self.hablando.discard(d)
            if d in self.dolls:
                asyncio.get_running_loop().create_task(self.soltar(d))
            if d in self.festejar:
                self.festejar.discard(d)
                asyncio.get_running_loop().create_task(self.festejo(d))

    async def lindo(self, doll: str, opciones, k=(0.7, 1.0)) -> None:
        info = self.dolls[doll]
        sabe = [(g, e) for g, e in opciones if g in info["gestos"]]
        if not sabe:
            return
        g, e = self.rng.choice(sabe)
        intent = {"gesto": g, "intensidad": round(self.rng.uniform(*k), 2)}
        if e in info["emociones"]:
            intent.update(emocion=e, duracion=4)
        await self.cuerpo(doll, **intent)

    async def manos(self, doll: str, tras: float = 0.0) -> None:
        """Las manos de hablar, más sueltas que las que le pone la consola (0.45). Solo si sigue hablando."""
        await asyncio.sleep(tras)
        if doll in self.hablando and "hablar_manos" in self.dolls[doll]["gestos"]:
            await self.cuerpo(doll, gesto="hablar_manos", intensidad=round(self.rng.uniform(0.7, 0.95), 2))

    @staticmethod
    def _manual(estado: dict) -> bool:
        """La maneja una persona (marioneta) o está leyendo un guion: no se le pisa el baile ni la pose."""
        return bool(estado.get("titere") or estado.get("escena"))

    @staticmethod
    def _quieta(estado: dict) -> bool:
        return bool(estado.get("dormida")) or bool(estado.get("titere")) or bool(estado.get("escena")) or (estado.get("modo") or "chat") != "chat"

    async def expresar(self, doll: str) -> None:
        """Un paso de expresividad, según qué está haciendo: habla, escucha a la otra, o nadie dice nada."""
        if doll in self.quietas:
            return
        info = self.dolls[doll]
        if doll in self.hablando:
            if self.rng.random() < 0.5:  # énfasis, y enseguida vuelven las manos
                await self.lindo(doll, ENFASIS, (0.6, 0.9))
                asyncio.get_running_loop().create_task(self.manos(doll, 2.0))
            else:  # otra cara, las manos siguen
                caras = [c for c in CARAS if c in info["emociones"]]
                if caras:
                    await self.cuerpo(doll, emocion=self.rng.choice(caras), intensidad=round(self.rng.uniform(0.7, 1), 2),
                                      duracion=round(self.rng.uniform(3, 5), 1))
                await self.manos(doll, 0.3)
        elif not self.libre(doll):
            return  # está pensando lo que va a decir: no se le pisa el gesto
        elif self.hablando:
            await self.lindo(doll, REACCIONES, (0.5, 0.85))
        elif self.rng.random() < 0.6:
            await self.lindo(doll, LINDOS)

    async def soltar(self, doll: str) -> None:
        """Terminó de hablar: que no le queden las manos de hablar puestas (si no empezó ya otro turno suyo)."""
        await asyncio.sleep(0.6)
        if self.libre(doll):
            await self.cuerpo(doll, soltar=True)

    async def festejo(self, conto: str) -> None:
        """Terminó el chiste: la otra se ríe o aplaude."""
        for otra in self.dolls:
            if otra != conto and self.libre(otra):
                await self.lindo(otra, FESTEJOS, (0.8, 1.0))

    # --- lo que hace sola ----------------------------------------------------------------
    async def gestos(self) -> None:
        while True:  # de a una por vez, al azar: cada una hace algo cada 5-9 s
            await asyncio.sleep(self.rng.uniform(*self.a.gesto))
            if self.dolls:
                await self.expresar(self.rng.choice(list(self.dolls)))

    async def bailes(self) -> None:
        await asyncio.sleep(2)
        while True:
            for d in self.dolls:  # de fondo no bailan: apenas cambian el peso de pierna, para no quedar duras
                if d in self.titeres:  # (a la marioneta no se le pisa el baile/pose que eligió quien la maneja)
                    continue
                await self.cuerpo(d, baile=self.a.fondo, tempo=40)
            if not self.a.baile[1]:
                return
            await asyncio.sleep(self.rng.uniform(*self.a.baile))
            libres = [d for d in self.dolls if d not in self.titeres]  # a las marionetas las baila quien las maneja
            quienes = libres if self.rng.random() < 0.6 else [self.rng.choice(libres or [""])]
            tempo = self.rng.randint(112, 132)
            log.info("bailan %s (%s bpm)", quienes, tempo)
            for d in quienes:
                if d:
                    await self.cuerpo(d, baile="fuerte", tempo=tempo)
            await asyncio.sleep(self.rng.uniform(10, 16))

    async def humor(self) -> None:
        if not self.a.chiste[1]:
            return
        await asyncio.sleep(self.a.primero)
        while True:
            for _ in range(30):  # espera un hueco (hasta 1 min); si no lo hay, entra igual cuando termine la que habla
                if not self.cola["actual"] and not self.cola["pendientes"] and not self.hablando:
                    break
                await asyncio.sleep(2)
            if not self._humor:
                base = {"bimbo": HUMOR_BIMBO, "dolls": HUMOR_DOLLS}.get(self.a.humor, HUMOR)
                pool = [h for h in base if self.sfw or not h[2]]
                self._humor = self.rng.sample(pool, len(pool))
            quien, pedido, solo_stream = self._humor.pop()
            if solo_stream and not self.sfw:  # la lista se armó en modo stream y ahora es el normal: se rearma
                self._humor = []
                continue
            nombres = {d: {"BL4CKROSE": "Rose"}.get(x["nombre"], x["nombre"]) for d, x in self.dolls.items()}
            pedido = pedido.format(joy=nombres.get("joy", "Joy"), bambi=nombres.get("bambi", "Bambi"))
            # si una duerme o está en trance/spa no se la saca con un chiste: ese pedido se saltea
            if not self.quietas and self.dolls and (quien == "ambas" or quien in self.dolls):
                log.info("humor → %s: %s", quien, pedido)
                self.festejar |= set(self.dolls) if quien == "ambas" else {quien}
                await self.enviar({"type": "msg", "doll": quien, "text": pedido})
            await asyncio.sleep(self.rng.uniform(*self.a.chiste))

    async def correr(self) -> None:
        tareas = [asyncio.create_task(f()) for f in (self.gestos, self.bailes, self.humor)]
        try:
            while True:
                try:
                    async with connect(self.a.url, open_timeout=10) as ws:
                        self.ws = ws
                        log.info("conectada a %s", self.a.url)
                        async for m in ws:
                            self.evento(json.loads(m))
                except OSError as e:
                    log.warning("sin consola (%s); reintento", e)
                except Exception as e:  # noqa: BLE001
                    log.warning("se cortó la consola (%s); reintento", e)
                self.ws = None
                await asyncio.sleep(3)
        finally:
            for t in tareas:
                t.cancel()
            try:  # al apagarla dejan de bailar
                async with connect(self.a.url, open_timeout=3) as ws:
                    for d in self.dolls:
                        await ws.send(json.dumps({"type": "cuerpo", "doll": d, "intent": {"baile": "no"}}))
                    await asyncio.sleep(0.3)
            except Exception:  # noqa: BLE001
                pass


def rango(s: str) -> tuple[float, float]:
    v = [float(x) for x in str(s).split(",")]
    return (v[0], v[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://127.0.0.1:8780/ws")
    ap.add_argument("--gesto", type=rango, default=(2.5, 4.5), help="segundos entre un gesto y el siguiente (de cualquiera)")
    ap.add_argument("--baile", type=rango, default=(300, 480), help="segundos entre un baile y el siguiente (0 = nunca)")
    ap.add_argument("--fondo", type=lambda v: v if v in ("no", "suave", "lento", "fuerte") else float(v), default=0.4,
                    help="movimiento de fondo, 0..1 (0.4: balanceo, cambia el peso de pierna; no: quieta)")
    ap.add_argument("--chiste", type=rango, default=(180, 300), help="segundos entre pedidos de humor (0 = ninguno)")
    ap.add_argument("--humor", choices=("stream", "bimbo", "dolls"), default="stream",
                    help="lista de pedidos de humor (bimbo: show 18+, en inglés; dolls: modo normal, el lore del Instituto)")
    ap.add_argument("--primero", type=float, default=20, help="segundos hasta el primer pedido de humor")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    async def run():
        t = asyncio.create_task(Animadora(args).correr())
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, t.cancel)
        try:
            await t
        except asyncio.CancelledError:
            pass
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
