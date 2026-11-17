#!/usr/bin/env sh

export WIFI_TEST_IP=${WIFI_TEST_IP:-1.1.1.1}

# Se actualiza a las 6:05 y a las 18:05 (5 minutos después de que el computador genera la portada).
export REFRESH_SCHEDULE=${REFRESH_SCHEDULE:-"5 6,18 * * *"}
export TIMEZONE=${TIMEZONE:-"America/Santiago"}

# Limpieza completa de la pantalla en cada actualización (evita imágenes fantasma).
export FULL_DISPLAY_REFRESH_RATE=${FULL_DISPLAY_REFRESH_RATE:-0}

# Importante: con 12 horas entre actualizaciones, kindle-dash mostraría su pantalla
# de "durmiendo" en vez del periódico. Este valor alto lo evita.
export SLEEP_SCREEN_INTERVAL=999999

export LOW_BATTERY_REPORTING=${LOW_BATTERY_REPORTING:-false}
export LOW_BATTERY_THRESHOLD_PERCENT=10
