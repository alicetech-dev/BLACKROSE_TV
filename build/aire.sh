#!/bin/bash
# BlackRose TV 2049 — estudio Unity AL AIRE: sin ventana (-batchmode), rinde en la AMD (Vulkan/Mesa, no toca la RTX) y manda
# el video por ffmpeg/VAAPI a udp://127.0.0.1:9036 → OBS «Estudio BRTV (Unity)». ./aire.sh [set]   (parar: ./aire.sh stop)
cd "$(dirname "$0")"
if [ "$1" = stop ]; then p=$(pgrep -f "^./BlackroseTV[.]x86_64 -batchmode"); [ -n "$p" ] && kill $p; exit 0; fi
pgrep -f "^./BlackroseTV[.]x86_64" >/dev/null && { echo "ya está corriendo"; exit 0; }
ICD=$(ls /usr/share/vulkan/icd.d/radeon_icd*.json 2>/dev/null | head -1)
VK_ICD_FILENAMES=$ICD VK_DRIVER_FILES=$ICD __GLX_VENDOR_LIBRARY_NAME=mesa DRI_PRIME=pci-0000_65_00_0 \
  nohup ./BlackroseTV.x86_64 -batchmode ${1:+-set $1} -logFile "$PWD/aire.log" >/dev/null 2>&1 &
echo "estudio al aire (pid $!) · log $PWD/aire.log"
