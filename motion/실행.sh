#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
PY=$(command -v python3 || command -v python)
[ -z "$PY" ] && { echo "파이썬이 없다. sudo apt install python3 python3-venv"; exit 1; }
"$PY" motion/start.py "$@"
