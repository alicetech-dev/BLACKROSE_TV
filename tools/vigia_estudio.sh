#!/usr/bin/env bash
# Vigila el estudio Unity de BlackRose TV (:8836). Si no responde 3 revisiones seguidas, lo relanza con aire.sh
# (máx. 1 vez cada 10 min y solo si hay >1,5 GB de RAM disponible; si no, el director sigue en TV NOCHE).
AIRE=~/BlackroseTV_build/aire.sh; fallas=0; ult=0
while true; do
  sleep 60
  if curl -s -m4 -o /dev/null http://127.0.0.1:8836/api/estado; then fallas=0; continue; fi
  fallas=$((fallas+1)); [ $fallas -lt 3 ] && continue
  ahora=$(date +%s); [ $((ahora-ult)) -lt 600 ] && continue
  disp=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  if [ "$disp" -lt 1500 ]; then echo "$(date +%T) estudio caído, RAM disponible ${disp} MB: no lo relanzo"; ult=$ahora; continue; fi
  echo "$(date +%T) estudio caído: relanzando (RAM ${disp} MB)"; "$AIRE" stop >/dev/null 2>&1; sleep 3
  setsid nohup "$AIRE" noticiario >/dev/null 2>&1 & ult=$ahora; fallas=0
done
