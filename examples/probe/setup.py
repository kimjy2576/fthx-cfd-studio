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

# ── 5. 존 타입 변경 (wall → inlet/outlet) ──────────────────
# 메싱에서 이름만 바꿨으므로 솔버에서는 전부 wall 로 들어옴.
# 실측: velocity_inlet 컬렉션이 비어 있어 BC 설정이 KeyError.
#       초기화도 "This case has no inlets & no outlets" 로 경고.
# → 먼저 타입을 바꿔야 BC 를 걸 수 있음.
def SETTINGS():
    """올바른 경로는 solver.settings.setup.
       (실측: solver.setup 은 'setup is deprecated. Use settings.setup')"""
    g = globals()
    for nm in ("solver", "session", "root"):
        o = g.get(nm)
        if o is None:
            continue
        st = getattr(o, "settings", None)
        if st is not None:
            return st
        if getattr(o, "setup", None) is not None:
            return o
    raise NameError("settings 객체를 찾지 못함")

def _zone_types():
    t = TUI()
    for zone, typ in (("air_inlet", "velocity-inlet"),
                      ("air_outlet", "pressure-outlet"),
                      ("ref_inlet_c01", "mass-flow-inlet"),
                      ("ref_outlet_c01", "pressure-outlet")):
        try_all("%s -> %s" % (zone, typ), [
            ("define.boundary_conditions.zone_type",
             lambda z=zone, y=typ: t.define.boundary_conditions.zone_type(z, y)),
            ("define.boundary-conditions.modify-zones.zone-type",
             lambda z=zone, y=typ:
                 t.define.boundary_conditions.modify_zones.zone_type(z, y)),
        ])
step("5. 존 타입 변경 (wall -> inlet/outlet)", _zone_types)

# ── 6. 포러스 존 ───────────────────────────────────────────
def _porous():
    """공기 코어를 포러스로. superficial velocity 기준.
       Laminar Zone 을 켜 포러스 내부의 가짜 난류점성을 막음."""
    print("    porosity %.6f · C2 %.2f 1/m · 1/alpha %.4e 1/m2"
          % (POROSITY, C2, 1.0 / ALPHA))
    czc = SETTINGS().setup.cell_zone_conditions
    fl = czc.fluid
    names = [n for n in list(fl) if "air_core" in n]
    print("    포러스 대상: %s" % names)
    for n in names:
        obj = fl[n]
        # 추측을 멈추고 실제 스키마를 캐냄 — get_state 가 정확한 키를 보여줌
        try:
            st = obj.get_state()
            print("    [스키마] get_state() 최상위 키:")
            for k in sorted(st):
                v = st[k]
                print("      %-34s %s" % (k, str(v)[:70]))
        except Exception as ex:
            print("    get_state 실패: %s" % ex)
        try:
            print("    child_names: %s" % list(obj.child_names)[:40])
        except Exception:
            pass
        try_all("porous %s" % n, [
            ("set_state(porous_zone)", lambda o=obj: o.set_state({
                "porous": True,
                "porosity": {"value": POROSITY},
                "viscous_resistance": {"direction_1": 1.0 / ALPHA,
                                       "direction_2": 1.0 / ALPHA,
                                       "direction_3": 1.0 / ALPHA},
                "inertial_resistance": {"direction_1": C2,
                                        "direction_2": C2,
                                        "direction_3": C2},
                "laminar": True})),
            ("porous=True 만", lambda o=obj: o.set_state({"porous": True})),
        ])
    print("    → GUI 확인용")
    print("      Viscous Resistance 1/alpha = %.4e 1/m2" % (1.0 / ALPHA))
    print("      Inertial Resistance C2     = %.4f 1/m" % C2)
    print("      Porosity                   = %.6f" % POROSITY)
    print("      Laminar Zone               = ON")
    print("      Relative Velocity Resistance Formulation = OFF (superficial)")
step("6. 포러스 존", _porous)

# ── 6b. 경계조건 ───────────────────────────────────────────
def _bc():
    bc = SETTINGS().setup.boundary_conditions
    for t_ in ("velocity_inlet", "pressure_outlet", "mass_flow_inlet", "wall"):
        c = getattr(bc, t_, None)
        try:
            ks = list(c) if c is not None else None
        except Exception:
            ks = "?"
        print("    %-18s %s" % (t_, str(ks)[:100]))

    if "air_inlet" in list(bc.velocity_inlet):
        obj = bc.velocity_inlet["air_inlet"]
        try:
            st = obj.get_state()
            print("    [스키마] air_inlet get_state():")
            for k in sorted(st):
                print("      %-30s %s" % (k, str(st[k])[:80]))
        except Exception as ex:
            print("    get_state 실패: %s" % ex)
        try:
            print("    child_names: %s" % list(obj.child_names)[:40])
        except Exception:
            pass
        try_all("공기 입구 %.2f m/s / %.1f K" % (V_FACE, T_AIR_IN), [
            ("momentum+thermal", lambda o=obj: o.set_state({
                "momentum": {"velocity_magnitude": {"value": V_FACE}},
                "thermal": {"t": {"value": T_AIR_IN}}})),
            ("flat", lambda o=obj: o.set_state({"velocity_magnitude": V_FACE,
                                               "t": T_AIR_IN})),
        ])
    else:
        print("    air_inlet 이 velocity_inlet 에 없음 — 5단계 타입 변경 확인")

    if "air_outlet" in list(bc.pressure_outlet):
        obj = bc.pressure_outlet["air_outlet"]
        try:
            print("    [스키마] air_outlet: %s" % sorted(obj.get_state())[:20])
        except Exception:
            pass
        try_all("공기 출구 0 Pa", [
            ("momentum", lambda o=obj: o.set_state({
                "momentum": {"gauge_pressure": {"value": 0.0}},
                "thermal": {"t": {"value": T_AIR_IN}}})),
            ("flat", lambda o=obj: o.set_state({"gauge_pressure": 0.0})),
        ])

    if "ref_inlet_c01" in list(bc.mass_flow_inlet):
        obj = bc.mass_flow_inlet["ref_inlet_c01"]
        try:
            print("    [스키마] ref_inlet: %s" % sorted(obj.get_state())[:20])
        except Exception:
            pass
        try_all("냉매 입구 %.5f kg/s / %.1f K" % (M_REF / N_CIRCUIT, T_REF), [
            ("momentum+thermal", lambda o=obj: o.set_state({
                "momentum": {"mass_flow_rate": {"value": M_REF / N_CIRCUIT}},
                "thermal": {"t": {"value": T_REF}}})),
        ])
step("6b. 경계조건", _bc)

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
    try_all("Coupled p-v", [
        ("settings.solution.methods",
         lambda: setattr(SETTINGS().solution.methods.p_v_coupling,
                         "flow_scheme", "Coupled")),
        ("tui p-v-coupling 24", lambda: t.solve.set.p_v_coupling(24)),
    ])
    try_all("2차 상류", [
        ("discretization", lambda: t.solve.set.discretization_scheme("mom", 1)),
    ])
step("8. 솔버", _solver)

# ── 9. 초기화 + 저장 ───────────────────────────────────────
def _init():
    t = TUI()
    try_all("초기화", [
        ("settings hybrid_initialize",
         lambda: SETTINGS().solution.initialization.hybrid_initialize()),
        ("tui hybrid", lambda: t.solve.initialize.hyb_initialization()),
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
