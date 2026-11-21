#!/usr/bin/env bash
# BlackRose TV 24/7 autónoma (guion fractal, 100 % local): jornada de 12:00 a 12:00, cartelera nueva cada día.
#   Servicios: llm4b (4B RTX :8089) · cerebro (:8087, 4B⇄9B ThinkPad) · tv-productor (fractal.py) · tv-noche (director de TV)
#              brtv-pensador (9B, pensamientos e investigación) · brtv-orquesta (vigilante) · japon-capa · brtv-overlay
#   ./tv.sh salud      estado de cada pieza (logs/salud.json, lo escribe la orquesta cada 30 s)
#   ./tv.sh jornada    muestra la cartelera de la jornada (--forzar la regenera)
#   ./tv.sh pensar     último pensamiento interno del 9B
#   ./tv.sh envivo [on|off]  on = la TV se aparta (stop) y el 4B deja la RTX libre para jugar; off = vuelve todo
#   ./tv.sh estado     qué está al aire, paquetes listos y últimas líneas del log
#   ./tv.sh start      prende Productor y Director (arrancan solos con el reloj)
#   ./tv.sh stop       los apaga y vuelve a la escena JOY DISCORD (las dolls siguen calladas)
#   ./tv.sh log        sigue el log del director
#   ./tv.sh cartelera  muestra la tarjeta de la cartelera 25 s
#   ./tv.sh hibernar [min]  LOW TOKENS: overlay rojo + silencio (solo contestan si les hablan, con el 9B); 10 min por defecto
#   ./tv.sh sala [hacker|joy]  cambia el entorno 3D de la escena SALA DE CONTROL en vivo (sin argumento: muestra el actual)
#   ./tv.sh dormir <min|HH:MM>  Alice duerme: cámara de circuito cerrado + cuenta regresiva en la SALA DE CONTROL · ./tv.sh despertar
#   ./tv.sh producir <bloque> [-f]   (re)genera el paquete de un bloque
cd "$(dirname "$0")" || exit 1
case "${1:-estado}" in
  start) systemctl --user start tv-productor tv-noche; ./tv.sh estado ;;
  stop)  systemctl --user stop tv-noche tv-productor; .venv/bin/python director/tv/obs_noche.py crear >/dev/null 2>&1
         curl -s -X POST localhost:8822/api/tv -d '{"modo":"idle"}' >/dev/null; echo "apagado" ;;
  log)   tail -n 40 -f logs/tv_noche.log ;;
  cartelera) curl -s -X POST localhost:8822/api/cartelera -d '{"mostrar":25}' >/dev/null; echo ok ;;
  hibernar) m="${2:-10}"; .venv/bin/python -c "import json,time,sys;t=time.time();json.dump({'inicio':t,'hasta':t+float(sys.argv[1])*60},open('director/tv/hibernacion.json','w'))" "$m"
         echo "LOW TOKENS · hibernación de $m min (se activa en cuanto una doll vaya a hablar); cancelar: ./tv.sh hibernar 0" ;;
  sala) if [ -n "$2" ]; then curl -s -X POST localhost:8830/api/sala -d "{\"sala\":\"$2\"}"; else curl -s localhost:8830/api/sala; fi; echo ;;
  dormir) a="$2"; case "$a" in *:*) b="{\"hasta\":\"$a\"}";; *) b="{\"minutos\":${a:-180}}";; esac; curl -s -X POST localhost:8830/api/sueno -d "$b"; echo ;;
  despertar) curl -s -X POST localhost:8830/api/sueno -d '{"dormida":false}'; echo ;;
  producir) shift; .venv/bin/python -m director.tv.fractal producir "$@" ;;
  salud) .venv/bin/python -c "
import json,urllib.request as u
d=json.load(open('logs/salud.json')); n=d.pop('nivel',None); t=d.pop('_t','?')
[print(('ok ' if v['ok'] else '!! ')+k.ljust(14), str(v['detalle'])[:70]) for k,v in d.items()]
if n: print(f\"NIVEL {n['n']} · {n['que']} {n['motivos'] or ''} · LLM: {n['llm_ultima_hora']} llamadas en {n['minutos_medidos']} min · en vivo: {n['envivo']}\")
try:
  c=json.load(u.urlopen('http://127.0.0.1:8797/estado',timeout=2)); print(f\"CHAT twitch: {c['twitch']} · youtube: {c['youtube']} · respondidos {c['respondidos']} (fijas {c['fijas']}, LLM {c['llm_llamadas']}, fallas {c['llm_fallas']})\")
except Exception as e: print('!! CHAT sin respuesta', e)
print('revisado', t)" ;;
  jornada) shift; .venv/bin/python -m director.tv.fractal jornada "$@" ;;
  pensar) tail -n 1 logs/pensamientos.jsonl | .venv/bin/python -c "import json,sys;d=json.loads(sys.stdin.read());print(d['t'],'·',d.get('animo'));print(d.get('pensamiento'));print('directriz:',d.get('directriz'))" ;;
  envivo) if [ "${2:-on}" = on ]; then touch logs/envivo; systemctl --user stop tv-noche; systemctl --user start brtv-orquesta brtv-chat
            echo "Alice en vivo: TV apartada (sin cambios de escena). Siguen el chat, el cerebro, el relé y el vigilante. Al terminar: ./tv.sh envivo off"
          else rm -f logs/envivo; systemctl --user start llm4b tv-noche brtv-orquesta brtv-chat; echo "vuelve la programación"; fi ;;
  *) echo "director: $(systemctl --user is-active tv-noche) · productor: $(systemctl --user is-active tv-productor) · hora $(date +%T)"
     [ -f director/tv/estado.json ] && echo "estado: $(cat director/tv/estado.json)"
     echo "paquetes:"; ls director/tv/noche/*/ 2>/dev/null | tr '\n' ' '; echo
     echo "--- log"; tail -n 12 logs/tv_noche.log 2>/dev/null ;;
esac
