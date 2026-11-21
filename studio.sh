#!/usr/bin/env bash
# Blackrose TV Studio — arranque con un solo comando.
#   ./studio.sh start [--no-abrir]   levanta el servidor (:8840) y abre /estudio en el navegador
#   ./studio.sh stop | estado | log
# Variables: BRTV_STUDIO_DATA (carpeta del proyecto, por defecto ~/BlackroseStudio/mi-canal),
#            BRTV_STUDIO_PUERTO (8840), BRTV_PY (intérprete de Python; por defecto .venv del repo o python3).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
PUERTO="${BRTV_STUDIO_PUERTO:-8840}"
DATOS="${BRTV_STUDIO_DATA:-$HOME/BlackroseStudio/mi-canal}"
PY="${BRTV_PY:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )}"
mkdir -p "$DATOS"
PID="$DATOS/.studio.pid"; LOG="$DATOS/studio.log"
URL="http://127.0.0.1:$PUERTO/estudio"

vivo() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }

case "${1:-start}" in
  start)
    if vivo; then echo "Ya está corriendo: $URL"; else
      "$PY" -c "import aiohttp" 2>/dev/null || { echo "Falta aiohttp: $PY -m pip install aiohttp"; exit 1; }
      BRTV_STUDIO_DATA="$DATOS" nohup "$PY" -m studio.servidor --puerto "$PUERTO" --proyecto "$DATOS" >>"$LOG" 2>&1 &
      echo $! >"$PID"
      for _ in $(seq 30); do curl -fs "http://127.0.0.1:$PUERTO/api/escena" >/dev/null 2>&1 && break; sleep 0.2; done
      vivo || { echo "No arrancó; mira $LOG"; exit 1; }
      echo "Studio en $URL  ·  salida para OBS: http://127.0.0.1:$PUERTO/salida"
    fi
    [ "${2:-}" = "--no-abrir" ] || (xdg-open "$URL" >/dev/null 2>&1 &) ;;
  stop)   vivo && kill "$(cat "$PID")" && echo "Detenido." || echo "No estaba corriendo."; rm -f "$PID" ;;
  estado) vivo && echo "Corriendo (pid $(cat "$PID")): $URL" || echo "Detenido." ;;
  log)    tail -n 40 "$LOG" ;;
  *)      echo "uso: $0 start [--no-abrir] | stop | estado | log"; exit 2 ;;
esac
