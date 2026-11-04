#!/bin/bash
# Arranca el backend y la cara de Nova. Ctrl+C detiene ambos.
cd "$(dirname "$0")" || exit 1
.venv/bin/python server.py &
server=$!
trap 'kill $server 2>/dev/null' EXIT
npm --prefix frontend run dev
