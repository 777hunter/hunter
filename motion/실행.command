#!/bin/bash
# 맥에서 이 파일을 더블클릭하면 실행된다.
# 처음 한 번은 Finder 에서 오른쪽 클릭 > 열기 를 해야 할 수 있다.
cd "$(dirname "$0")/.." || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "파이썬이 없다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행할 것."
  read -r -p "엔터를 누르면 닫힌다 "
  exit 1
fi
"$PY" motion/start.py "$@"
echo
read -r -p "엔터를 누르면 닫힌다 "
