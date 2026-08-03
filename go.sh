#!/usr/bin/env bash
# 한 번에: 갱신 → 정리 → 제출 → 완료 대기 → 결과 출력
#
#   ./go.sh                 probe · 32 core
#   ./go.sh tutorial 8      케이스 · 코어
#   ./go.sh probe 32 --no-pull
#
# 완료를 기다렸다가 결과까지 찍으므로 bjobs 를 손으로 볼 필요가 없음.

set -uo pipefail
CASE=${1:-probe}
CORES=${2:-32}
NOPULL=""
for a in "$@"; do [ "$a" = "--no-pull" ] && NOPULL=1; done

ROOT="$(cd "$(dirname "$0")" && pwd)"
DIR="$ROOT/examples/$CASE"
[ -d "$DIR" ] || { echo "케이스 없음: $DIR"; echo "가능: $(ls "$ROOT/examples" | tr '\n' ' ')"; exit 1; }

hr() { printf '%.0s─' {1..64}; echo; }

# ── 1. 최신 코드 ──────────────────────────────────────────
if [ -z "$NOPULL" ]; then
  echo "[1/5] git pull"
  git -C "$ROOT" pull --quiet --ff-only 2>&1 | sed 's/^/      /' || \
    echo "      (건너뜀 — 로컬 수정이 있거나 네트워크 문제)"
  echo "      $(git -C "$ROOT" log --oneline -1)"
else
  echo "[1/5] git pull 건너뜀"
fi

# ── 2. 이전 결과 정리 ─────────────────────────────────────
echo "[2/5] 이전 결과 정리"
rm -f "$DIR"/*.trn "$DIR"/*.lsflog "$DIR"/*.msh.h5 "$DIR"/hosts.* 2>/dev/null
rm -rf "$DIR"/*_workflow_files 2>/dev/null

# ── 3. 제출 ───────────────────────────────────────────────
cd "$DIR"
echo "[3/5] 제출 — $CASE · ${CORES} core"
OUT=$(fluent 3d -meshing -g -t"$CORES" -i mesh.py 2>&1)
echo "$OUT" | sed 's/^/      /'
JOB=$(echo "$OUT" | grep -oE 'Job <[0-9]+>' | grep -oE '[0-9]+' | head -1)

# ── 4. 완료 대기 ──────────────────────────────────────────
if [ -z "$JOB" ]; then
  # 큐가 아니라 그 자리에서 실행된 경우 — 이미 끝났음
  echo "[4/5] 큐 제출 없음 (직접 실행 완료)"
else
echo "[4/5] 완료 대기 (작업 $JOB · Ctrl+C 로 중단해도 작업은 계속됨)"
T0=$SECONDS; LAST=""
while true; do
  ST=$(bjobs -noheader -o stat "$JOB" 2>/dev/null | tr -d ' ')
  [ -z "$ST" ] && { echo "      완료 ($((SECONDS-T0))초)"; break; }
  case "$ST" in
    DONE|EXIT) echo "      $ST ($((SECONDS-T0))초)"; break;;
  esac
  if [ "$ST" != "$LAST" ]; then
    printf "      %s" "$ST"
    [ "$ST" = "PEND" ] && printf " — %s" \
      "$(bjobs -p "$JOB" 2>/dev/null | sed -n '3p' | sed 's/^ *//' | cut -c1-50)"
    echo; LAST=$ST
  else
    printf "."
  fi
  sleep 5
done
fi
sleep 3   # 트랜스크립트가 닫히기를 기다림

# ── 5. 결과 ───────────────────────────────────────────────
echo "[5/5] 결과"; hr
"$ROOT/examples/check.sh"
hr
LOG=$(ls -t *.trn 2>/dev/null | head -1)
if [ -n "$LOG" ]; then
  FAIL=$(grep -c "^<<< FAIL" "$LOG" 2>/dev/null | tr -dc '0-9'); FAIL=${FAIL:-0}
  MISS=$(grep -c "^    건너뜀" "$LOG" 2>/dev/null | tr -dc '0-9'); MISS=${MISS:-0}
  if [ "$FAIL" -eq 0 ] && [ "$MISS" -eq 0 ] && [ -f mesh_labeled.msh.h5 ]; then
    echo "판정: 통과 — 실패 단계 없음, 좌표 매칭 전부 성공, 메시 저장됨"
  else
    echo "판정: 확인 필요 — 실패단계 $FAIL · 매칭실패 $MISS · 메시 $([ -f mesh_labeled.msh.h5 ] && echo 있음 || echo 없음)"
  fi
  echo "로그 전문: $DIR/$LOG"
fi
