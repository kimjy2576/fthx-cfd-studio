#!/usr/bin/env bash
# 최근 실행 결과 요약
LOG=$(ls -t *.trn 2>/dev/null | head -1)
[ -z "$LOG" ] && { echo "로그 없음 — 아직 실행 전이거나 대기 중"; exit 1; }
echo "=== 단계 ==="
grep -E "^<<<" "$LOG" | tail -20
echo "=== 결과 ==="
grep -E "cells were created|Total Number of Cell Zones|Orthogonal Quality" "$LOG"
if grep -qE "LABEL 완료|BSEP 완료" "$LOG" 2>/dev/null; then
  echo "=== 프로브 (분리 시도 상세) ==="
  # cmd: 마커 다음에 오는 ERROR 까지 같이 보여줌 — 시도별 오류 귀속
  grep -nE "^    대상:|^      cmd:|^      존 수|^    \[OK\]|^    \[--\]|^    \[!!\]|일치 존|기대 면적|이미 있음|하위:|후보|^  == |오브젝트|object|ERROR|Error object" "$LOG" \
    | grep -vE "^\s*[0-9]+:\.\.\." | head -120
fi
if grep -q "SETUP 완료" "$LOG" 2>/dev/null; then
  echo "=== SETUP (M3) ==="
  sed -n '/5. 포러스 계수/,/<<</p' "$LOG" | grep -E "porosity|Viscous|Inertial|Porosity|Laminar|Relative"
  grep -E "^ +모드:|^ +hv =|^ +정의:|^ +\[OK\]|^ +\[--\]|^ +\[확인\]|^ +\[스키마|^ +---|^ +sources|^ +dir\(|^ +list\(" "$LOG" | head -30
  if grep -q "12. 반복" "$LOG" 2>/dev/null; then
    echo "--- 수렴 (M4) ---"
    echo "  residual (마지막 5줄):"
    grep -E "^ *[0-9]+ +[0-9]\.[0-9]{4}e[+-][0-9]{2}" "$LOG" | tail -5
    echo "  물리량:"
    sed -n '/13. 수렴 물리량/,/<<< OK   13/p' "$LOG" \
      | grep -E "^ +[0-9-]+\.[0-9]|Net|Average|Weighted" | head -12
    echo "  리포트 API (다음 라운드 확정용):"
    sed -n '/11. 리포트 정의/,/<<< OK   11/p' "$LOG" | grep -E "하위:|\[--\]|\[OK\]|스키마" | head -8
  fi
  echo "--- 성능 지표 (M5) ---"
  ROOT=$(cd "$(dirname "$0")/.." && pwd)
  if [ -f results.csv ]; then cat results.csv; fi
  # pydantic 없이 도는 버전 — Fluent 서버에 pip 이 없어도 됨
  python "$ROOT/scripts/post_standalone.py" . 2>/dev/null \
    || python3 "$ROOT/scripts/post_standalone.py" . 2>/dev/null \
    || echo "  (지표 계산 실패 — results.csv 나 case.json 확인)"
  echo "--- 포러스 최종 상태 ---"
  grep -E "^    \[최종\]|^           " "$LOG" | head -8
  echo "--- API 스키마 ---"
  grep -E "^    \[스키마\]|^      [a-z_]+ +|^    child_names|^    포러스 대상|^    velocity_inlet|^    pressure_outlet|^    mass_flow_inlet" "$LOG" | head -60
  grep -E "^    \[OK\].*cas\.h5|^    \[!!\]" "$LOG"
fi
echo "=== 존 목록 / 분리 ==="
grep -E "^      (fluid_|solid_|wall|interior)|^    (velocity_inlet|pressure_outlet|symmetry|periodic|interior|분리 대상|분리 후)" "$LOG" | head -30
echo "=== 좌표 매칭 ==="
grep -E "^    (face_seeds|입구면 기대|후보 wall|surface_integrals|시험:|x 좌표 획득|좌표를 못)|^      .* x .* area |^    cell_(inlet|outlet) " "$LOG" | head -40
sed -n '/face_seeds 좌표 매칭/,/face_seeds 목록/p' "$LOG" | grep -E "거리|임계값"
echo "=== 오류 ==="
# '...' 로 시작하는 줄은 Fluent 이 저널 코드를 되비춘 것이지 실제 오류가 아님
grep -iE "error|sigsegv" "$LOG" | grep -vE "^(\.\.\.|>>>)" | head -10 \
  || echo "  없음"
echo "=== 저장 확인 (저널이 직접 확인한 것) ==="
sed -n '/17. 저장 파일 확인/,/^<<</p' "$LOG" | grep -E "작업 폴더|\[OK\]|\[!!\]"
echo "=== 파일 ==="
ls -lt --time-style=+%m-%d\ %H:%M *.msh.h5 "$LOG" 2>/dev/null | head -5
# 로그는 실행이 끝난 뒤 닫히므로 항상 메시보다 최신임.
# 이전 실행 파일인지는 '저장 확인' 항목의 [OK] 경로·시각으로 판단할 것.
for f in mesh.msh.h5 mesh_labeled.msh.h5; do
  [ -f "$f" ] || echo "  ⚠ $f 없음"
done
[ -f case.cas.h5 ] && ls -lh --time-style=+%m-%d\ %H:%M case.cas.h5
