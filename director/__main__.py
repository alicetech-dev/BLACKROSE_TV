"""Director de las dolls (consola). La web UI (fase 4) usa las mismas piezas.

  .venv/bin/python -m director                      # todas las dolls de dolls.yaml
  .venv/bin/python -m director --dolls joy --sin-sink

Escribí un mensaje; contesta la doll que nombres ("joy, ..." / "bambi: ...") o la última con la que hablaste.
Después, con probabilidad `opinar`, la otra agrega un comentario. Comandos: /dolls /estado /callar /salir.
Requiere: el agente (`python -m agente serve`) y un joy_vmc por doll.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import re
import sys

import yaml

from .audio import Reproductor
from .clientes import Cerebro, Cuerpo
from .doll import DollRunner
from .voz import PRESETS, crear, mantener_xtts, principal_xtts

HERE = os.path.dirname(os.path.abspath(__file__))


def _fundir(base: dict, extra: dict) -> dict:
    """Mezcla recursiva: lo de `extra` pisa a `base` (los diccionarios se combinan, lo demás se reemplaza)."""
    for k, v in extra.items():
        base[k] = _fundir(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def cargar(path: str | None = None, perfil: str | None = None) -> dict:
    """El yaml de la consola. Un `perfil` (argumento o DOLLS_PERFIL) aplica encima la sección `perfiles.<perfil>`:
    `ligero` = Joy con IA y BL4CKROSE en marioneta, voz gTTS y Claude de cerebro (sin GPU). `solo` deja solo esas dolls; `voz` se suma a la de cada una."""
    with open(path or os.path.join(HERE, "dolls.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    perfil = perfil or os.environ.get("DOLLS_PERFIL") or ""
    cfg["perfil"] = perfil or "habitual"
    if perfil:
        extra = dict((cfg.get("perfiles") or {}).get(perfil) or {})
        if not extra:
            raise SystemExit(f"el perfil «{perfil}» no existe en {path or 'dolls.yaml'} (sección perfiles:)")
        solo, voz = extra.pop("solo", None), extra.pop("voz", None)
        voz = os.environ.get("DOLLS_VOZ") or voz       # nombre de un preset de voz.py (gtts | xtts) o un diccionario
        voz = PRESETS[voz] if isinstance(voz, str) else voz
        _fundir(cfg, extra)
        if solo:
            cfg["dolls"] = {d: v for d, v in cfg["dolls"].items() if d in solo}
        for d in cfg["dolls"].values():
            if voz:
                d["voz"] = {**d.get("voz", {}), **voz}
    return cfg


async def armar(cfg: dict, ids: list[str] | None = None, sink: str | None = "config", emitir=None,
                on_segmento=None) -> dict[str, DollRunner]:
    """on_segmento(doll, texto, origen): quién decide si se dice un segmento de autonomía (la consola lo pasa por su
    fila y puede cambiarlo por una réplica a la otra). Sin él, se dice directo."""
    dolls: dict[str, DollRunner] = {}

    def al_evento(ev: dict) -> None:
        # segmentos de autonomía (vida/sleep) que genera el agente solo: la doll los dice en voz alta
        if ev.get("type") == "segmento" and ev.get("doll") in dolls:
            if on_segmento:
                on_segmento(ev["doll"], ev["text"], ev.get("origen", ""))
            else:
                asyncio.get_running_loop().create_task(dolls[ev["doll"]].decir(ev["text"], ev.get("origen", "")))
        elif ev.get("type") == "investigacion" and ev.get("doll") in dolls and ev.get("consulta"):
            dolls[ev["doll"]]._evento("biblioteca", consulta=ev["consulta"], nota=ev.get("nota", ""),
                                      texto=(ev.get("texto") or "")[:400])
    cerebro = Cerebro(cfg["agente"], al_evento=al_evento)
    info = await cerebro.pedir({"cmd": "dolls"})
    nombres = {d["id"]: d["name"] for d in info.get("dolls", [])} if info.get("type") == "dolls" else {}
    if cfg.get("sfw") and not info.get("sfw"):
        # en vivo no se arriesga: sin un agente que confirme que corre un pack SFW, el director no prende ninguna doll
        raise SystemExit(f"modo SFW: el agente de {cfg['agente']} "
                         + (f"corre el pack «{info.get('pack', '?')}», que no es SFW" if nombres else "no responde")
                         + ". Apagá todo (dolls.sh stop) y prendé con: dolls.sh start --sfw")
    if not nombres:
        logging.warning("el agente no respondió en %s (%s): las dolls arrancan dormidas", cfg["agente"], info.get("error"))
    a = cfg.get("audio", {})
    microfono = asyncio.Lock()  # una sola habla a la vez: se turnan
    for did, dc in cfg["dolls"].items():
        if ids and did not in ids:
            continue
        if nombres and did not in nombres:
            logging.warning("el agente no tiene la doll %s (EXTRA_DOLLS); la salteo", did)
            continue
        repro = Reproductor(bloque_ms=a.get("bloque_ms", 20), adelanto_ms=a.get("adelanto_ms", 40),
                            sink=a.get("sink") if sink == "config" else sink)
        repro.iniciar()
        runner = DollRunner(did, dc.get("nombre") or nombres.get(did, did), cerebro, Cuerpo(dc["cuerpo"]), None, repro,
                            {**dc, "cuerpo": dc.get("cuerpo_desc", ""), "llm_directo": cfg.get("llm_directo")},
                            emitir=emitir)
        runner.voz = crear(dc.get("voz", {}), cfg["xtts_url"],
                           avisar=lambda que, r=runner: r._evento("aviso", texto={"xtts_frio": "XTTS arrancando: hablo con gTTS mientras tanto",
                                                                                   "xtts_error": "XTTS falló: uso gTTS",
                                                                                   "xtts_esperando": "XTTS arrancando (~30 s): espero para hablar con su voz"}.get(que, que)))
        runner.lock = microfono
        await runner.preparar()
        dolls[did] = runner
    for did, r in dolls.items():
        r.companeras = {o: x for o, x in dolls.items() if o != did}
        asyncio.create_task(r.vivir())
    await cerebro.conectar()
    xtts = next((x for x in (principal_xtts(r.voz) for r in dolls.values()) if x), None)
    async def precalentar():
        # primero el 4B (si XTTS arranca antes, el pedido al 4B espera su arranque en frío), después XTTS
        await cerebro.pedir({"cmd": "health"})
        if xtts:  # un solo XTTS para todas: se mantiene despierto mientras charlen
            await mantener_xtts(xtts, lambda: max(r.ultimo_turno for r in dolls.values()),
                                activa=lambda: any(principal_xtts(r.voz) is xtts for r in dolls.values()))
    asyncio.create_task(precalentar())
    return dolls


def alias(did: str, r) -> set[str]:
    """Con qué nombres se la llama: su id, su nombre y los `alias` de su configuración."""
    return {did, r.estado.nombre.lower(), *(str(a).lower() for a in getattr(r, "cfg", {}).get("alias", []))}


def destinataria(texto: str, dolls: dict[str, DollRunner], ultima: str) -> tuple[str, str]:
    """La doll nombrada al principio del mensaje ("joy, ...", "bambi: ...") o la última."""
    for did, r in dolls.items():
        for a in alias(did, r):
            m = re.match(rf"\s*@?{re.escape(a)}\b[\s,:]*", texto, re.I)
            if m:
                return did, texto
    return ultima, texto


def nombrada(texto: str, dolls: dict[str, DollRunner]) -> str | None:
    """La doll nombrada en CUALQUIER parte del mensaje (chat del canal: "hola joy!", "qué opina blackrose?")."""
    for did, r in dolls.items():
        if any(re.search(rf"(?<!\w){re.escape(a)}(?!\w)", texto, re.I) for a in alias(did, r)):
            return did
    return None


async def consola(cfg: dict, dolls: dict[str, DollRunner]) -> None:
    ultima = next(iter(dolls))
    loop = asyncio.get_running_loop()
    print(f"Dolls: {', '.join(f'{d} ({r.estado.nombre})' for d, r in dolls.items())}. Escribí; /salir para terminar.")
    while True:
        linea = await loop.run_in_executor(None, sys.stdin.readline)
        if not linea:
            return
        texto = linea.strip()
        if not texto:
            continue
        if texto in ("/salir", "/quit"):
            return
        if texto == "/estado":
            for r in dolls.values():
                print(r.estado)
            continue
        if texto == "/callar":
            for r in dolls.values():
                r.repro.callar()
            continue
        ultima, texto = destinataria(texto, dolls, ultima)
        await dolls[ultima].turno(texto, cfg["usuario"])
        otras = [d for d in dolls if d != ultima]
        if otras and random.random() < float(cfg.get("opinar", 0)):
            await dolls[random.choice(otras)].turno("", cfg["usuario"], chime_in=True)


def imprimir(ev: dict) -> None:
    t = ev["type"]
    if t == "frase":
        print(f"  {ev['doll']}: {ev['texto']}", flush=True)
    elif t in ("aviso", "dormida", "despierta"):
        print(f"  [{ev['doll']}] {t}: {ev.get('texto', '')}", flush=True)
    elif t == "fin":
        print(f"  [{ev['doll']}] tiempos {ev['tiempos']} · caché {ev.get('cache')}", flush=True)


async def main_async(args) -> None:
    cfg = cargar(args.config)
    dolls = await armar(cfg, args.dolls.split(",") if args.dolls else None, None if args.sin_sink else "config",
                        emitir=imprimir)
    if not dolls:
        sys.exit("no hay dolls")
    try:
        await consola(cfg, dolls)
    finally:
        for r in dolls.values():
            r.repro.cerrar()


def main() -> None:
    ap = argparse.ArgumentParser(prog="director", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--dolls", help="ids separados por coma (por defecto todas)")
    ap.add_argument("--sin-sink", action="store_true", help="audio a la salida por defecto, sin el sink 'dolls'")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
