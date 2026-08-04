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
ITER     = int(os.environ.get("FTHX_ITER", "0"))

# ── 유도된 값 ──────────────────────────────────────────────
POROSITY  = 0.930063
C2        = 80.8536          # 1/m, 유동 방향
ALPHA     = 1.951828e-07          # m2, 투과율
H_EFF     = 59.7969       # W/m2K (핀효율 반영)
A_V       = 1150.99         # 1/m
HV        = 68825.64   # W/m3K
V_FACE    = 2.0               # m/s
D_H_AIR   = 0.002299   # m, 공기측 수력직경
DP_PRED   = 4.1574        # Pa, closure 가 예측한 코어 압력강하
CASE_NAME = "tutorial_1tube"
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

def try_all(label, trials, stop_on_success=True):
    """성공하면 즉시 반환. 실측에서 iterate 가 두 번 돌아 1155회까지 간 적 있음
       (iter_count= 로 성공했는데 다음 후보도 실행됨)."""
    print("  == " + label)
    for name, fn in trials:
        try:
            out = fn()
            if out is False:
                print("    [--] " + name + " -> False")
                continue
            print("    [OK] " + name)
            if stop_on_success:
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
        # 실측 스키마: porous_zone = {'porous': False}, general = {'laminar': False}
        try_all("porous 켜기 %s" % n, [
            ("porous_zone.porous = True",
             lambda o=obj: o.porous_zone.set_state({"porous": True})),
        ])
        # 켠 뒤 하위 키가 드러남 — 스키마를 다시 찍어 확정
        try:
            pz = obj.porous_zone.get_state()
            print("    [스키마] porous_zone (켠 뒤):")
            for k in sorted(pz):
                print("      %-36s %s" % (k, str(pz[k])[:64]))
            print("    child_names: %s" % list(obj.porous_zone.child_names)[:40])
        except Exception as ex:
            print("    porous_zone get_state 실패: %s" % ex)
        try_all("Laminar Zone", [
            ("general.laminar = True",
             lambda o=obj: o.general.set_state({"laminar": True})),
        ])
        # ⚠ 기본값이 True(=physical velocity). superficial 기준으로 산출한
        #   C2 를 쓰려면 반드시 꺼야 함. 켜두면 dP 가 1/gamma^2 배 어긋남.
        try_all("superficial velocity (relative_velocity_... = False)", [
            ("relative_velocity_resistance_formulation=False",
             lambda o=obj: o.porous_zone.set_state(
                 {"relative_velocity_resistance_formulation": False})),
        ])
        try_all("점성 저항 1/alpha = %.4e 1/m2" % (1.0 / ALPHA), [
            ("viscous_resistance direction_1..3",
             lambda o=obj: o.porous_zone.set_state({"viscous_resistance": {
                 "direction_1": 1.0 / ALPHA,
                 "direction_2": 1.0 / ALPHA,
                 "direction_3": 1.0 / ALPHA}})),
        ])
        try_all("관성 저항 C2 = %.4f 1/m" % C2, [
            ("inertial_resistance direction_1..3",
             lambda o=obj: o.porous_zone.set_state({"inertial_resistance": {
                 "option": "constant",
                 "direction_1": C2, "direction_2": C2, "direction_3": C2}})),
        ])
        try_all("공극률 %.6f" % POROSITY, [
            ("fluid_porosity option/value",
             lambda o=obj: o.porous_zone.set_state({"fluid_porosity": {
                 "option": "constant", "value": POROSITY}})),
        ])
        try:
            pz = obj.porous_zone.get_state()
            print("    [최종] porous=%s  gamma=%s" % (
                pz.get("porous"), pz.get("fluid_porosity")))
            print("           1/alpha=%s" % str(pz.get("viscous_resistance"))[:70])
            print("           C2     =%s" % str(pz.get("inertial_resistance"))[:70])
            print("           relative_velocity_...=%s"
                  % pz.get("relative_velocity_resistance_formulation"))
        except Exception:
            pass
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
        # 실측 스키마: thermal = {'temperature': {'option':'value','value':300}}
        try_all("공기 입구 온도 %.1f K" % T_AIR_IN, [
            ("thermal.temperature.value",
             lambda o=obj: o.thermal.set_state(
                 {"temperature": {"option": "value", "value": T_AIR_IN}})),
        ])
        try:
            mo = obj.momentum.get_state()
            print("    [스키마] air_inlet.momentum:")
            for k in sorted(mo):
                print("      %-36s %s" % (k, str(mo[k])[:64]))
        except Exception as ex:
            print("    momentum get_state 실패: %s" % ex)
        try_all("공기 입구 %.2f m/s" % V_FACE, [
            ("momentum.velocity_magnitude",
             lambda o=obj: o.momentum.set_state(
                 {"velocity_magnitude": {"option": "value", "value": V_FACE}})),
        ])
        try_all("난류 (I=5%%, 수력직경)", [
            ("turbulence intensity+hydraulic_diameter",
             lambda o=obj: o.turbulence.set_state({
                 "turbulent_specification": "Intensity and Hydraulic Diameter",
                 "turbulent_intensity": 0.05,
                 "hydraulic_diameter": D_H_AIR})),
        ])
    else:
        print("    air_inlet 이 velocity_inlet 에 없음 — 5단계 타입 변경 확인")

    if "air_outlet" in list(bc.pressure_outlet):
        obj = bc.pressure_outlet["air_outlet"]
        try:
            print("    [스키마] air_outlet: %s" % sorted(obj.get_state())[:20])
        except Exception:
            pass
        try:
            print("    [스키마] air_outlet.momentum: %s"
                  % sorted(obj.momentum.get_state())[:16])
        except Exception:
            pass
        try_all("공기 출구 0 Pa / %.1f K" % T_AIR_IN, [
            ("momentum.gauge_pressure", lambda o=obj: o.momentum.set_state(
                {"gauge_pressure": {"option": "value", "value": 0.0}})),
        ])
        try_all("출구 역류 온도", [
            ("thermal.temperature", lambda o=obj: o.thermal.set_state(
                {"temperature": {"option": "value", "value": T_AIR_IN}})),
        ])

    if "ref_inlet_c01" in list(bc.mass_flow_inlet):
        obj = bc.mass_flow_inlet["ref_inlet_c01"]
        try:
            print("    [스키마] ref_inlet: %s" % sorted(obj.get_state())[:20])
        except Exception:
            pass
        try:
            print("    [스키마] ref_inlet.momentum: %s"
                  % sorted(obj.momentum.get_state())[:16])
        except Exception:
            pass
        try_all("냉매 입구 %.5f kg/s" % (M_REF / N_CIRCUIT), [
            ("momentum.mass_flow_rate", lambda o=obj: o.momentum.set_state(
                {"mass_flow_rate": {"option": "value",
                                    "value": M_REF / N_CIRCUIT}})),
        ])
        try_all("냉매 입구 온도 %.1f K" % T_REF, [
            ("thermal.temperature", lambda o=obj: o.thermal.set_state(
                {"temperature": {"option": "value", "value": T_REF}})),
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

# ── 11. 리포트 정의 (수렴 판정용 물리량) ──────────────────
# residual 만으로는 수렴을 판정할 수 없음. 물리량이 안정됐는지 봐야 함.
def _reports():
    S = SETTINGS()
    rd = getattr(getattr(S, "solution", None), "report_definitions", None)
    if rd is None:
        print("    report_definitions 없음")
        return
    avail = [x for x in dir(rd) if not x.startswith("_")]
    print("    report_definitions 하위 (%d):" % len(avail))
    for i in range(0, len(avail), 5):
        print("      " + ", ".join(avail[i:i + 5]))
    try:
        print("    child_names: %s" % list(rd.child_names))
    except Exception:
        pass
    # 실측: surface_areaavg / surface_massavg / flux 는 없음. 위 목록에서
    # 실제 이름을 골라 쓸 것. 아래는 흔한 후보들.
    # 실측 확정: rd.surface / rd.flux (surface_areaavg 아님)
    specs = [
        ("dp_air", ["surface"],
         {"report_type": "surface-areaavg", "field": "pressure",
          "surface_names": ["air_inlet"]}),
        ("t_air_out", ["surface"],
         {"report_type": "surface-massavg", "field": "temperature",
          "surface_names": ["air_outlet"]}),
        ("m_air_in", ["flux"],
         {"report_type": "flux-massflow", "zone_names": ["air_inlet"]}),
    ]
    for nm, kinds, args in specs:
        obj = None
        for k in kinds:
            obj = getattr(rd, k, None)
            if obj is not None:
                print("    %s -> rd.%s" % (nm, k))
                break
        if obj is None:
            print("    [--] %-16s (%s 전부 없음)" % (nm, kinds))
            continue
        got, _ = try_all("리포트 %s (%s)" % (nm, kind), [
            ("create+set", lambda o=obj, n=nm, a=args: (
                o.create(n), o[n].set_state(a))[1]),
            ("create only", lambda o=obj, n=nm: o.create(n)),
        ])
        if got:
            try:
                print("      [스키마] %s" % str(obj[nm].get_state())[:200])
            except Exception:
                pass
step("11. 리포트 정의", _reports)

# ── 12. 반복 ───────────────────────────────────────────────
def _iterate():
    S = SETTINGS()
    rc = getattr(getattr(S, "solution", None), "run_calculation", None)
    if rc is not None:
        print("    run_calculation 하위: %s"
              % [x for x in dir(rc) if not x.startswith("_")][:18])
    try_all("반복 %d 회" % ITER, [
        ("settings run_calculation.iterate",
         lambda: rc.iterate(iter_count=ITER)),
        ("settings iterate(N)", lambda: rc.iterate(ITER)),
        ("tui solve.iterate", lambda: TUI().solve.iterate(ITER)),
    ])

if ITER > 0:
    step("12. 반복 %d회" % ITER, _iterate)

    # ── 13. 수렴 판정 ──────────────────────────────────────
    def _converged():
        """물리량 추이로 판정. residual 은 참고용."""
        S = SETTINGS()
        try:
            rp = S.solution.report_definitions
            for n in ("dp_air", "t_air_out", "m_air_in"):
                try:
                    print("    %-12s %s" % (n, str(rp[n].get_state())[:120]))
                except Exception:
                    pass
        except Exception as ex:
            print("    리포트 조회 실패: %s" % ex)
        # 면적분으로 직접 뽑기 — 리포트 정의가 실패해도 이건 됨
        t = TUI()
        for label, path, args in (
                ("공기 입구 압력", "report.surface_integrals.area_weighted_avg",
                 ("air_inlet", "()", "pressure", "no")),
                ("공기 출구 압력", "report.surface_integrals.area_weighted_avg",
                 ("air_outlet", "()", "pressure", "no")),
                ("공기 출구 온도", "report.surface_integrals.mass_weighted_avg",
                 ("air_outlet", "()", "temperature", "no")),
        ):
            o = t
            for part in path.split("."):
                o = getattr(o, part, None)
                if o is None:
                    break
            if o is None:
                print("    [--] %s (%s 없음)" % (label, path))
                continue
            try_all(label, [(path, lambda o=o, a=args: o(*a))])
    print("    ── 대조 ──")
    print("    closure 예측 코어 dP = %.3f Pa" % DP_PRED)
    print("    (위 입구압력 - 출구압력 과 비교. 오차가 크면 포러스 계수 확인)")

def _results_csv():
    """면적분 값을 CSV 로 직접 씀. 로그 파싱은 형식이 바뀌면 깨지므로 안 함.
       Fluent 의 surface_integrals 는 값을 파일로 저장할 수 있음."""
    t = TUI()
    si = t.report.surface_integrals
    tmp = os.path.join(_HERE, "_si.txt")
    specs = [
        ("p_air_in",  "area_weighted_avg", ["air_inlet"],  "pressure"),
        ("p_air_out", "area_weighted_avg", ["air_outlet"], "pressure"),
        ("t_air_out", "mass_weighted_avg", ["air_outlet"], "temperature"),
        ("t_ref_out", "mass_weighted_avg", ["ref_outlet_c01"], "temperature"),
    ]
    vals = {}
    for key, fn_name, surfs, field in specs:
        fn = getattr(si, fn_name, None)
        if fn is None:
            print("    [--] %s (%s 없음)" % (key, fn_name))
            continue
        if os.path.exists(tmp):
            os.remove(tmp)
        ok = False
        for args in ((surfs[0], "()", field, "yes", tmp, "yes"),
                     (surfs[0], "()", field, "yes", tmp)):
            try:
                fn(*args)
                ok = True
                break
            except Exception as ex:
                last = "%s: %s" % (type(ex).__name__, str(ex)[:80])
        if not ok:
            print("    [--] %s 파일저장 실패 (%s)" % (key, last))
            continue
        try:
            with open(tmp) as f:
                txt = f.read()
            num = None
            for line in txt.splitlines():
                parts = line.split()
                for tok in parts[::-1]:
                    try:
                        num = float(tok)
                        break
                    except ValueError:
                        continue
                if num is not None:
                    break
            vals[key] = num
            print("    %-12s %s" % (key, num))
        except Exception as ex:
            print("    [--] %s 파싱 실패: %s" % (key, ex))

    out = os.path.join(_HERE, "results.csv")
    cols = ["case", "p_air_in", "p_air_out", "t_air_out", "t_ref_out"]
    with open(out, "w") as f:
        f.write(",".join(cols) + chr(10))
        f.write(",".join([CASE_NAME] + [
            ("" if vals.get(c) is None else "%.6g" % vals[c])
            for c in cols[1:]]) + chr(10))
    print("    [OK] results.csv 저장: %s" % out)
    for c in cols[1:]:
        print("      %-12s %s" % (c, vals.get(c)))
    step("13. 수렴 물리량", _converged)
    step("14. results.csv", _results_csv)

    step("15. 데이터 저장",
         lambda: TUI().file.write_data(CASE_OUT.replace(".cas", ".dat")))

def _verify():
    import time
    print("    저널 폴더: " + _HERE)
    files = [MESH_IN, CASE_OUT]
    if ITER > 0:
        files.append(CASE_OUT.replace(".cas", ".dat"))
        files.append(os.path.join(_HERE, "results.csv"))
    for f in files:
        if os.path.exists(f):
            st = os.stat(f)
            print("    [OK] %-28s %8.1f MB  %s" % (
                os.path.basename(f), st.st_size / 1e6,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
        else:
            print("    [!!] %-28s 없음" % os.path.basename(f))
step("16. 파일 확인", _verify)

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
