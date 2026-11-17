#!/usr/bin/env sh
# Descarga la portada desde tu computador.
# CAMBIA 192.168.1.100 por la IP que muestra periodico.py al iniciar.
"$(dirname "$0")/../xh" -d -q -o "$1" get http://192.168.1.100:8080/portada.png
