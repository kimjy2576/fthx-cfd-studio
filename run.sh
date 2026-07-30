#!/usr/bin/env bash
# FT-HX CFD Studio — macOS / Linux 실행
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  ============================================"
echo "   FT-HX CFD Studio"
echo "  ============================================"
echo

PY=$(command -v python3 || command -v python) || {
  echo "  [오류] Python 을 찾을 수 없음 (3.10 이상 필요)"; exit 1; }

VPY=.venv/bin/python
if [ ! -x "$VPY" ]; then
  echo "  [1/3] 가상환경 생성 중..."
  "$PY" -m venv .venv
else
  echo "  [1/3] 가상환경 확인됨"
fi

if ! "$VPY" -c "import fastapi, uvicorn, pydantic, numpy, scipy" >/dev/null 2>&1; then
  echo "  [2/3] 의존성 설치 중... cadquery 가 커서 몇 분 걸릴 수 있음"
  "$VPY" -m pip install --upgrade pip -q
  "$VPY" -m pip install -r requirements.txt
else
  echo "  [2/3] 의존성 확인됨"
fi
"$VPY" -c "import cadquery" >/dev/null 2>&1 || echo "        · cadquery 없음 - STEP 생성 비활성"
"$VPY" -c "import CoolProp"  >/dev/null 2>&1 || echo "        · CoolProp 없음 - 물성 조회 비활성"

echo "  [3/3] 서버 시작 - http://127.0.0.1:8020  (Ctrl+C 로 종료)"
echo
exec "$VPY" run.py --reload "$@"
