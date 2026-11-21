#!/usr/bin/env bash
# Salida de audio de las dolls en PipeWire (con pactl, la capa de compatibilidad de PulseAudio):
#   director --(PULSE_SINK=dolls)--> null-sink "dolls" --monitor--> OBS (fuente: "Monitor of Dolls")
#                                                      \--loopback--> tus auriculares (la salida por defecto)
# No es persistente: se pierde al reiniciar la sesión. `audio_setup.sh quitar` lo deshace.
# `audio_setup.sh mudo` saca solo el loopback (voces en el celular del visor VR); sin argumentos vuelve a ponerlo.
set -euo pipefail
SINK=${SINK:-dolls}

quitar() {
    for id in $(pactl list short modules | awk -v s="$SINK" '($2=="module-null-sink" && $3 ~ "sink_name="s) || ($2=="module-loopback" && $3 ~ "source="s".monitor") {print $1}'); do
        pactl unload-module "$id"
    done
    echo "quitado: $SINK"
}

if [[ "${1:-}" == "quitar" ]]; then quitar; exit 0; fi
if [[ "${1:-}" == "mudo" ]]; then   # las voces van al celular (visor VR): sin loopback a la PC, OBS sigue captando
    for id in $(pactl list short modules | awk -v s="$SINK" '$2=="module-loopback" && $3 ~ "source="s".monitor" {print $1}'); do
        pactl unload-module "$id"
    done
    echo "la PC ya no reproduce las voces ($SINK sigue para OBS). Para volver: $0"; exit 0
fi

if pactl list short sinks | awk '{print $2}' | grep -qx "$SINK"; then
    echo "ya existe el sink $SINK"
else
    pactl load-module module-null-sink sink_name="$SINK" sink_properties=device.description=Dolls >/dev/null
    echo "creado el sink $SINK"
fi
if pactl list short modules | grep -q "module-loopback.*source=$SINK.monitor"; then
    echo "ya existe el loopback a los auriculares"
else
    # latency_msec bajo: lo que oís vos queda casi alineado con lo que capta OBS (los auriculares bluetooth suman lo suyo)
    pactl load-module module-loopback source="$SINK.monitor" latency_msec=30 >/dev/null
    echo "loopback $SINK.monitor -> salida por defecto ($(pactl get-default-sink))"
fi
echo "En OBS: Fuente > Captura de entrada de audio > 'Monitor of Dolls'."
