#!/usr/bin/env bash
# 최근 실행 결과 요약
LOG=$(ls -t *.trn 2>/dev/null | head -1)
[ -z "$LOG" ] && { echo "로그 없음 — 아직 실행 전이거나 대기 중"; exit 1; }
echo "=== 단계 ==="
grep -E "^<<<" "$LOG" | tail -20
echo "=== 결과 ==="
grep -E "cells were created|Total Number of Cell Zones|Orthogonal Quality" "$LOG"
if grep -q "SETUP 완료" "$LOG" 2>/dev/null; then
  echo "=== SETUP (M3) ==="
  sed -n '/5. 포러스 계수/,/<<</p' "$LOG" | grep -E "porosity|Viscous|Inertial|Porosity|Laminar|Relative"
  sed -n '/7. 열 모델/,/<<</p' "$LOG" | grep -E "모드|h_eff|a_v|hv|단열"
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
  if [ -f results.csv ]; then
    echo "--- 결과 (M5) ---"
    cat results.csv
    echo "  → 성능 지표:  python scripts/post.py examples/<case>/results.csv --preset <case>"
  fi
  echo "--- 포러스 최종 상태 ---"
  grep -E "^    \[최종\]|^           " "$LOG" | head -8
  echo "--- API 스키마 ---"
  grep -E "^    \[스키마\]|^      [a-z_]+ +|^    child_names|^    포러스 대상|^    velocity_inlet|^    pressure_outlet|^    mass_flow_inlet" "$LOG" | head -60
  grep -E "^    \[OK\].*cas\.h5|^    \[!!\]" "$LOG"
fi
echo "=== 좌표 매칭 ==="
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
