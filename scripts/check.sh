#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  전체 검증 파이프라인 — 사용자는 git pull 후 이것 하나만 실행
#
#    (Windows)  cd fthx-cfd-studio ; git pull
#    (WSL)      bash scripts/check.sh
#
#  수행: pytest → STL 생성+surfaceCheck → 케이스 생성 → 메싱+검산
#  실패하면 해당 로그의 마지막 30줄을 자동으로 출력하고 멈춤.
#  마지막에 "ALL OK" 가 나오면 그 출력 전체를 회신하면 됨.
# ═══════════════════════════════════════════════════════════════
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

# ── 파이썬 선택: Windows venv 우선, 없으면(순수 리눅스) python3
if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"
elif python3 -c "import cadquery" 2>/dev/null; then PY=python3
else
    echo "[중단] 파이썬 환경 없음 — Windows 에서 run.bat 을 1회 실행해 .venv 생성"
    exit 2
fi

# ── OpenFOAM 환경
if ! command -v surfaceCheck >/dev/null 2>&1; then
    set +u                       # OpenFOAM bashrc 는 unbound 변수를 사용함
    for rc in /usr/lib/openfoam/openfoam*/etc/bashrc; do
        [ -f "$rc" ] && source "$rc" && break
    done
    set -u
fi
command -v surfaceCheck >/dev/null 2>&1 || { echo "[중단] OpenFOAM 없음 (WSL 에서 실행 중인지 확인)"; exit 2; }

step() { echo; echo "════ $* ════"; }
die()  { echo; echo "[중단] $1"
         [ -n "${2:-}" ] && [ -f "$2" ] && { echo "── ${2##*/} 마지막 30줄 ──"; tail -30 "$2"; }
         exit 1; }

step "1/4 회귀 테스트 (pytest) — CAD 테스트 포함 수 분 소요, 점(.)이 진행 표시"
# 빠른 반복:  FTHX_PYTEST_K="FoamCase" bash scripts/check.sh
"$PY" -m pytest tests/ -q ${FTHX_PYTEST_K:+-k "$FTHX_PYTEST_K"} \
    2>&1 | tee /tmp/fthx_pytest.log
[ "${PIPESTATUS[0]}" -eq 0 ] || die "pytest 실패" /tmp/fthx_pytest.log


step "2/4 STL 생성 + surfaceCheck 교차검증"
"$PY" scripts/make_stl.py > /tmp/fthx_stl.log 2>&1 \
    || die "make_stl 실패" /tmp/fthx_stl.log
grep "^\[OK\]" /tmp/fthx_stl.log
bash scripts/verify_stl.sh out_foam || die "surfaceCheck FAIL — 위 [FAIL] 로그 참조"

step "3/4 케이스 생성 (tutorial)"
"$PY" scripts/make_case.py tutorial > /tmp/fthx_case.log 2>&1 \
    || die "make_case 실패" /tmp/fthx_case.log
grep -E "^\[OK\]|level:" /tmp/fthx_case.log

step "4/4 메싱 + 검산 (~/cases/case_tutorial)"
CASE="$HOME/cases/case_tutorial"
rm -rf "$CASE" && mkdir -p "$HOME/cases" && cp -r out_foam/case_tutorial "$CASE"
if ! ( cd "$CASE" && ./Allrun.mesh ) | tee /tmp/fthx_mesh.log; then
    failed=$(grep -oE "log\.[A-Za-z]+" /tmp/fthx_mesh.log | tail -1)
    die "메싱 실패" "$CASE/${failed:-log.snappyHexMesh}"
fi
grep -q "Mesh OK" /tmp/fthx_mesh.log || die "checkMesh 불합격" "$CASE/log.checkMesh"

# cellZone 0 검사
if grep -E "^  [a-z_0-9]+: 0$" /tmp/fthx_mesh.log; then
    die "cellZone 셀 수 0 — 존 형성 실패" "$CASE/log.snappyHexMesh"
fi

echo
echo "══════════════════════════════════"
echo " ALL OK — 이 출력 전체를 복사해 회신"
echo "══════════════════════════════════"
