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
    g = globals()
    root = g.get("solver") or g.get("setup") or g.get("root")
    czc = None
    for path in ("setup.cell_zone_conditions", "cell_zone_conditions"):
        o = root
        for part in path.split("."):
            o = getattr(o, part, None)
            if o is None:
                break
        if o is not None:
            czc = o
            print("    셀존 경로: " + path)
            break
    if czc is not None:
        fl = getattr(czc, "fluid", None)
        if fl is not None:
            try:
                names = [n for n in list(fl) if "air_core" in n]
            except Exception:
                names = []
            print("    포러스 대상: %s" % names)
            for n in names:
                try_all("porous %s" % n, [
                    ("set_state", lambda n=n: fl[n].set_state({
                        "porous": True,
                        "porous_zone": {
                            "porosity": POROSITY,
                            "direction_1_viscous_resistance": 1.0 / ALPHA,
                            "direction_2_viscous_resistance": 1.0 / ALPHA,
                            "direction_3_viscous_resistance": 1.0 / ALPHA,
                            "direction_1_inertial_resistance": C2,
                            "direction_2_inertial_resistance": C2,
                            "direction_3_inertial_resistance": C2,
                        },
                        "laminar": True})),
                    ("porous flag only",
                     lambda n=n: setattr(fl[n], "porous", True)),
                ])
    print("    → GUI: Cell Zone Conditions > fluid_air_core* > Porous Zone")
    print("      Viscous Resistance 1/alpha = %.4e 1/m2" % (1.0 / ALPHA))
    print("      Inertial Resistance C2     = %.4f 1/m" % C2)
    print("      Porosity                   = %.6f" % POROSITY)
    print("      Laminar Zone               = ON")
    print("      Relative Velocity Resistance Formulation = OFF (superficial)")
step("5. 포러스 계수 (값 출력)", _porous)

# ── 6. 설정 객체 탐색 ──────────────────────────────────────
# TUI 경로 추측은 메싱에서 이미 실패했음: getattr 이 없는 이름에도 빈 메뉴를
# 돌려주고 호출 시 "'TUIMenu' object has no attribute" 가 남.
# (실측: tui.define.boundary_conditions.velocity_inlet 없음)
# → globals 의 solver 설정 객체를 직접 훑어 실제 경로를 확정한다.
def _probe_api():
    g = globals()
    for nm in ("solver", "setup", "root"):
        o = g.get(nm)
        if o is None:
            continue
        ns = [n for n in dir(o) if not n.startswith("_")]
        print("    %-10s %-28s %s" % (nm, str(type(o))[:28], ns[:14]))
        for sub in ("setup", "boundary_conditions", "cell_zone_conditions"):
            c = getattr(o, sub, None)
            if c is not None:
                cn = [n for n in dir(c) if not n.startswith("_")]
                print("      .%-22s %s" % (sub, cn[:18]))
step("6a. 설정 객체 탐색", _probe_api)

def _bc_zones():
    """존 이름이 솔버에서도 유지되는지 + BC 설정 경로 찾기."""
    g = globals()
    root = g.get("solver") or g.get("setup") or g.get("root")
    bc = None
    for path in ("setup.boundary_conditions", "boundary_conditions"):
        o = root
        for part in path.split("."):
            o = getattr(o, part, None)
            if o is None:
                break
        if o is not None:
            bc = o
            print("    BC 경로: " + path)
            break
    if bc is None:
        print("    BC 객체를 찾지 못함")
        return
    for t in ("velocity_inlet", "pressure_outlet", "wall", "mass_flow_inlet"):
        c = getattr(bc, t, None)
        if c is None:
            print("      %-18s 없음" % t)
            continue
        try:
            keys = list(c)
        except Exception:
            keys = "?"
        print("      %-18s 존: %s" % (t, str(keys)[:120]))
    globals()["_BC"] = bc
step("6b. 경계조건 존 목록", _bc_zones)

def _set_bc():
    bc = globals().get("_BC")
    if bc is None:
        print("    BC 객체 없음 — 6b 결과 확인 필요")
        return
    try_all("공기 입구 %s m/s, %.1f K" % (V_FACE, T_AIR_IN), [
        ("velocity_inlet['air_inlet'] = dict",
         lambda: bc.velocity_inlet["air_inlet"].set_state({
             "momentum": {"velocity_magnitude": {"value": V_FACE}},
             "thermal": {"t": {"value": T_AIR_IN}}})),
        ("velocity_inlet['air_inlet'].momentum",
         lambda: setattr(bc.velocity_inlet["air_inlet"].momentum
                         .velocity_magnitude, "value", V_FACE)),
    ])
    try_all("공기 출구 0 Pa gauge", [
        ("pressure_outlet['air_outlet'] = dict",
         lambda: bc.pressure_outlet["air_outlet"].set_state({
             "momentum": {"gauge_pressure": {"value": 0.0}},
             "thermal": {"t": {"value": T_AIR_IN}}})),
    ])
step("6c. 경계조건 설정", _set_bc)

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
