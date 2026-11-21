#!/bin/bash
# BlackRose TV 2049 — estudio Unity. ./estudio.sh [set]   (API :8836: /api/set?n=… /api/cam?n=… /api/titulares?t=a|b /api/medio?img=…)
cd "$(dirname "$0")"
pgrep -f "^./BlackroseTV[.]x86_64" >/dev/null && { echo "ya está corriendo"; exit 0; }
nohup ./BlackroseTV.x86_64 -screen-width 1920 -screen-height 1080 -screen-fullscreen 0 ${1:+-set $1} -logFile "$PWD/estudio.log" >/dev/null 2>&1 &
echo "estudio en marcha (pid $!) · log $PWD/estudio.log"
