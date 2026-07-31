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
grep -iE "error|sigsegv" "$LOG" | head -10
echo "=== 파일 ==="
ls -lh *.msh.h5 2>/dev/null || echo "메시 파일 없음"
