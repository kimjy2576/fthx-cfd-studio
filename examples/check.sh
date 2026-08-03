#!/usr/bin/env bash
# 최근 실행 결과 요약
LOG=$(ls -t *.trn 2>/dev/null | head -1)
[ -z "$LOG" ] && { echo "로그 없음 — 아직 실행 전이거나 대기 중"; exit 1; }
echo "=== 단계 ==="
grep -E "^<<<" "$LOG" | tail -20
echo "=== 결과 ==="
grep -E "cells were created|Total Number of Cell Zones|Orthogonal Quality" "$LOG"
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
