# -*- coding: utf-8 -*-
# FT-HX CFD Studio — Fluent 솔버 저널 (M3 SETUP)
#
#   fluent 3ddp -g -t32 -i setup.py
#
# 값은 형상·운전 조건에서 유도됨 (fthx.closure). 손으로 고칠 것 없음.
#   Re_Dc 2141  j 0.01349  f 0.01548   (plain x plain factor (임시))
#   포러스  C2 80.9 1/m · alpha 1.952e-07 m2 · gamma 0.9301
#   전열    h 69.6 → eta_o 0.8591 → h_eff 59.8 W/m2K
#           a_v 1151 1/m → hv 68,826 W/m3K
#
# ⚠ 포러스 존은 Fluent 기본이 superficial velocity 임. physical 로 바꾸면
#   ΔP 가 1/gamma^2 배 어긋남. 아래 설정은 superficial 기준임.

import os
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

MESH_IN  = os.path.join(_HERE, r"mesh_labeled.msh.h5")
CASE_OUT = os.path.join(_HERE, r"case.cas.h5")
ITER     = 0

# ── 유도된 값 ──────────────────────────────────────────────
POROSITY  = 0.930063
C2        = 80.8536          # 1/m, 유동 방향
ALPHA     = 1.951828e-07          # m2, 투과율
H_EFF     = 59.7969       # W/m2K (핀효율 반영)
A_V       = 1150.99         # 1/m
HV        = 68825.64   # W/m3K
V_FACE    = 2.0               # m/s
T_AIR_IN  = 300.15    # K
T_REF     = 280.15  # K
M_REF     = 0.03              # kg/s (전체)
N_CIRCUIT = 1
K_TUBE    = 386.0              # W/mK
THERMAL   = "equilibrium"
ZONES     = {"porous": ["fluid_air_core*"], "air_fluid": ["fluid_air_up*", "fluid_air_down*", "fluid_air_core*"], "ref_fluid": ["fluid_ref*", "fluid_bend*"], "solid": ["solid_tube*", "solid_bend*", "solid_casing*"]}

def step(label, fn):
    print("=" * 60)
    print(">>> " + label)
    try:
        fn()
        print("<<< OK   " + label)
        return True
    except Exception as e:
        print("<<< FAIL " + label + " : " + type(e).__name__ + ": " + str(e)[:300])
        traceback.print_exc()
        return False

def TUI():
    g = globals()
    for nm in ("tui", "solver", "meshing", "session", "root"):
        o = g.get(nm)
        if o is None:
            continue
        if nm == "tui":
            return o
        t = getattr(o, "tui", None)
        if t is not None:
            return t
    raise NameError("TUI 진입점 없음. globals: "
                    + ", ".join(sorted(k for k in g if not k.startswith("_")))[:400])

def try_all(label, trials):
    print("  == " + label)
    for name, fn in trials:
        try:
            out = fn()
            if out is False:
                print("    [--] " + name + " -> False")
                continue
            print("    [OK] " + name)
            return name, out
        except Exception as ex:
            print("    [--] " + name + " : " + type(ex).__name__ + ": " + str(ex)[:100])
    return None, None

# ── 1. 메시 읽기 ───────────────────────────────────────────
step("1. 메시 읽기", lambda: TUI().file.read_case(MESH_IN))

# ── 2. 존 목록 확인 ────────────────────────────────────────
def _zones():
    TUI().define.boundary_conditions.list_zones()
step("2. 존 목록", _zones)

# ── 3. 모델 ────────────────────────────────────────────────
def _models():
    t = TUI()
    t.define.models.energy("yes", "no", "no", "no", "yes")
    t.define.models.viscous.kw_sst("yes")
step("3. 에너지 + k-omega SST", _models)

# ── 4. 물성 ────────────────────────────────────────────────
def _materials():
    t = TUI()
    try_all("공기 (이상기체)", [
        ("air ideal-gas", lambda: t.define.materials.change_create(
            "air", "air", "yes", "ideal-gas", "no", "no", "no", "no", "no", "no")),
    ])
    try_all("구리 (관벽)", [
        ("copper", lambda: t.define.materials.copy("solid", "copper")),
    ])
step("4. 물성", _materials)

# ── 5. 포러스 존 ───────────────────────────────────────────
def _porous():
    """공기 코어를 포러스로. superficial velocity 기준.
       Laminar Zone 을 켜 포러스 내부의 가짜 난류점성을 막음."""
    print("    porosity %.6f · C2 %.2f 1/m · alpha %.3e m2" % (POROSITY, C2, ALPHA))
    print("    → GUI: Cell Zone Conditions > fluid_air_core* > Porous Zone")
    print("      Viscous Resistance 1/alpha = %.4e 1/m2" % (1.0 / ALPHA))
    print("      Inertial Resistance C2     = %.4f 1/m" % C2)
    print("      Porosity                   = %.6f" % POROSITY)
    print("      Laminar Zone               = ON")
    print("      Relative Velocity Resistance Formulation = OFF (superficial)")
step("5. 포러스 계수 (값 출력)", _porous)

# ── 6. 경계조건 ────────────────────────────────────────────
def _bc():
    t = TUI()
    try_all("공기 입구", [
        ("velocity-inlet air_inlet",
         lambda: t.define.boundary_conditions.velocity_inlet(
             "air_inlet", "no", "no", "yes", "yes", "no", V_FACE, "no", 0,
             "no", "no", "yes", 5, 10, "yes", T_AIR_IN)),
    ])
    try_all("공기 출구", [
        ("pressure-outlet air_outlet",
         lambda: t.define.boundary_conditions.pressure_outlet(
             "air_outlet", "yes", "no", 0, "no", T_AIR_IN, "no", "yes",
             "no", "no", "yes", 5, 10, "yes", "no", "no", "no")),
    ])
    print("    냉매 입구 %d개 · 회로당 %.5f kg/s" % (N_CIRCUIT, M_REF / N_CIRCUIT))
step("6. 경계조건", _bc)

# ── 7. 열 모델 안내 ────────────────────────────────────────
def _thermal():
    print("    모드: " + THERMAL)
    if THERMAL == "equilibrium":
        print("    단일 온도 포러스 + 체적 열원")
        print("      h_eff = %.2f W/m2K (핀효율 반영)" % H_EFF)
        print("      a_v   = %.1f 1/m" % A_V)
        print("      hv    = %.1f W/m3K  → 에너지 소스: hv*(T_wall - T)" % HV)
    elif THERMAL == "netm":
        print("    2온도(NETM) — 고체상↔관벽 접합 미검증. equilibrium 권장")
    else:
        print("    단열 — 압력강하만")
step("7. 열 모델", _thermal)

# ── 8. 솔버 설정 ───────────────────────────────────────────
def _solver():
    t = TUI()
    try_all("pseudo-transient", [
        ("solve/set/p-v-coupling 24",
         lambda: t.solve.set.p_v_coupling(24)),
    ])
    try_all("2차 상류", [
        ("discretization", lambda: t.solve.set.discretization_scheme("mom", 1)),
    ])
step("8. 솔버", _solver)

# ── 9. 초기화 + 저장 ───────────────────────────────────────
def _init():
    t = TUI()
    try_all("초기화", [
        ("hybrid", lambda: t.solve.initialize.hyb_initialization()),
        ("standard", lambda: t.solve.initialize.initialize_flow()),
    ])
step("9. 초기화", _init)

step("10. 케이스 저장", lambda: TUI().file.write_case(CASE_OUT))

if ITER > 0:
    step("11. 반복 %d회" % ITER, lambda: TUI().solve.iterate(ITER))
    step("12. 데이터 저장",
         lambda: TUI().file.write_data(CASE_OUT.replace(".cas", ".dat")))

def _verify():
    import time
    print("    저널 폴더: " + _HERE)
    for f in (MESH_IN, CASE_OUT):
        if os.path.exists(f):
            st = os.stat(f)
            print("    [OK] %-28s %8.1f MB  %s" % (
                os.path.basename(f), st.st_size / 1e6,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
        else:
            print("    [!!] %-28s 없음" % os.path.basename(f))
step("13. 파일 확인", _verify)

print("=" * 60)
print("SETUP 완료. 포러스 존 설정은 위 5단계 출력값을 확인할 것")
print("=" * 60)

# 솔버는 저널 끝에서 스스로 종료하지 않음. 명시적으로 나가야 LSF 작업이 끝남
# (메싱은 "Halting due to end of file on input" 으로 자동 종료됨).
try:
    TUI().exit()
except Exception:
    try:
        exit()
    except Exception:
        pass
