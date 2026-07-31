#!/usr/bin/env bash
# 예제 케이스 실행 — Fluent 외에는 아무것도 필요 없음
#   ./run.sh probe 8
set -e
CASE=${1:-probe}
CORES=${2:-8}
cd "$(dirname "$0")/$CASE"
echo "케이스 $CASE · $CORES core · $(pwd)"
fluent 3d -meshing -g -t"$CORES" -i mesh.py
echo
echo "제출됨. 확인:"
echo "  bjobs"
echo "  cd $(pwd) && ../check.sh"
