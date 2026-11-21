#!/usr/bin/env python3
"""Noticiero: le pasa a las dolls (consola del director, ws://127.0.0.1:8780/ws) una noticia a la vez para que la
discutan TURNOS turnos y después pasa a la siguiente; al terminar la lista vuelve a empezar.
  ~/joy_vmc/.venv/bin/python ~/joy_vmc/tools/noticiero.py [archivo] [turnos]
Se corta con Ctrl+C o matando el proceso (la charla en curso la frena el botón Parar de la consola)."""
import asyncio, json, os, sys
from websockets.asyncio.client import connect

ARCH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), 'noticias_semana.txt')
TURNOS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
UNA = os.environ.get('UNA_VUELTA') == '1'          # UNA_VUELTA=1: lee la lista una vez y termina

async def main():
    noticias = [l.strip() for l in open(ARCH, encoding='utf-8') if l.strip() and not l.startswith('#')]
    i = 0
    while True:
        try:
            async with connect('ws://127.0.0.1:8780/ws', max_size=None) as ws:
                while True:
                    tema = os.environ.get('PREFIJO', 'Noticia de la semana: ') + noticias[i % len(noticias)]
                    print(f'[{i % len(noticias) + 1}/{len(noticias)}] {tema[:90]}…', flush=True)
                    await ws.send(json.dumps({'type': 'conversar', 'tema': tema, 'turnos': TURNOS}))
                    empezo = False
                    async for m in ws:                     # espera a que esa charla termine
                        d = json.loads(m)
                        c = d.get('conv') if isinstance(d, dict) else None
                        if d.get('type') == 'conv' and c:
                            if c.get('activa') and c.get('tema') == tema: empezo = True
                            elif empezo and not c.get('activa'): break
                    i += 1
                    if UNA and i >= len(noticias): print('fin de la lista', flush=True); return
                    await asyncio.sleep(8)                 # respiro entre noticias
        except (OSError, Exception) as e:                  # el director se reinició: reconectar y seguir
            print('reconectando:', type(e).__name__, flush=True); await asyncio.sleep(5)

asyncio.run(main())
