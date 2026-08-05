# -*- coding: utf-8 -*-
# FT-HX CFD Studio — 주기 단위셀 (핀 실형상)
#
#   fluent 3ddp -g -t8 -i cell_setup.py
#
# 도메인 x 176.0 · y 25.40 (Pt/2) · z 1.814 (Fp/2) mm
# 네 측면 모두 대칭면 — 주기 경계 불필요
# Re_Dh 489 (laminar) → 난류 모델 끔
# 셀 추정 1502k · h_xy 0.25 · z 10+2층

import os
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

MESH_IN  = os.path.join(_HERE, r"cell.msh.h5")
CASE_OUT = os.path.join(_HERE, r"cell.cas.h5")
ITER     = int(os.environ.get("FTHX_ITER", "0"))
U_MAX    = 2.869315     # m/s, 최소유동면적 기준
V_FACE   = 2.000000    # m/s, 전면속도 (입구 BC)
T_IN     = 300.15       # K
T_WALL   = 280.15     # K, 관벽·핀뿌리 등온
AREA     = 0.001936552            # m2, 공기측 전열면적
LAMINAR  = True
CASE     = "cell_plain_cell"
FACE_SEEDS = {"cell_inlet": [0.0, 12.7, 1.3894642857142858], "cell_outlet": [176.0, 12.7, 1.3894642857142858]}
INLET_AREA_MM2 = 43.1619

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
    for nm in ("tui", "solver", "session", "root"):
        o = g.get(nm)
        if o is None:
            continue
        if nm == "tui":
            return o
        t = getattr(o, "tui", None)
        if t is not None:
            return t
    raise NameError("TUI 진입점 없음")

def SETTINGS():
    g = globals()
    for nm in ("solver", "session", "root"):
        o = g.get(nm)
        if o is not None and getattr(o, "settings", None) is not None:
            return o.settings
    raise NameError("settings 없음")

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
            print("    [--] " + name + " : " + type(ex).__name__ + ": " + str(ex)[:110])
    return None, None

step("1. 메시 읽기", lambda: TUI().file.read_case(MESH_IN))
step("2. 존 목록", lambda: TUI().define.boundary_conditions.list_zones())

def _models():
    t = TUI()
    t.define.models.energy("yes", "no", "no", "no", "yes")
    if LAMINAR:
        try_all("층류", [("viscous.laminar", lambda: t.define.models.viscous.laminar("yes"))])
    else:
        try_all("k-omega SST", [("kw_sst", lambda: t.define.models.viscous.kw_sst("yes"))])
step("3. 에너지 + 점성 모델", _models)

def SOLVER_TUI(cmd):
    """솔버에서 TUI 문자열 실행. 후보를 순서대로 시도."""
    g = globals()
    last = None
    for nm in ("solver", "session", "root"):
        o = g.get(nm)
        if o is None:
            continue
        for attr in ("execute_tui", "exec_tui"):
            fn = getattr(o, attr, None)
            if fn is None:
                continue
            try:
                return fn(cmd)
            except Exception as ex:
                last = "%s.%s: %s" % (nm, attr, str(ex)[:90])
    raise NameError("solver execute_tui 없음 (%s)" % last)

def _separate_faces():
    """존 목록 확인만. 분리는 불필요함이 확인됨.

    실측 존 목록:
      fluid_cell_up-solid:1      +  fluid_cell_up-solid:36958
      fluid_cell_core-solid:1    +  fluid_cell_core-solid:50009
      fluid_cell_core-solid-2-:1 +  fluid_cell_core-solid-2-:58611
      fluid_cell_down-solid:1    +  fluid_cell_down-solid:49349
    바디마다 이미 두 존으로 나뉘어 있음. '-2-' 는 코어 공기가 핀 위/아래
    두 덩이로 갈린 것 — 형상이 의도대로 만들어진 증거.
    separate-face-zone-by-angle / sep-face-zone-by-angle 은 둘 다 없음.
    """
    S = SETTINGS()
    bc = S.setup.boundary_conditions
    for t_ in ("wall", "velocity_inlet", "pressure_outlet",
               "symmetry", "periodic", "interior"):
        c = getattr(bc, t_, None)
        try:
            zs = list(c) if c is not None else []
        except Exception as ex:
            print("    %-16s !! %s" % (t_, str(ex)[:80]))
            continue
        print("    %-16s %d개" % (t_, len(zs)))
        for z in zs:
            print("      %s" % z)

def _match_and_rename():
    """면적 + 좌표로 입출구 존을 찾아 이름을 붙임.

    입구면 면적은 형상에서 알고 있음(y x z 에서 핀 두께 제외).
    좌표를 못 얻어도 면적만으로 후보가 좁혀짐.
    """
    S = SETTINGS()
    bc = S.setup.boundary_conditions
    print("    face_seeds: %s" % FACE_SEEDS)
    print("    입구면 기대 면적 %.2f mm2" % INLET_AREA_MM2)
    try:
        zones = [z for z in list(bc.wall) if "shadow" not in z]
    except Exception as ex:
        print("    wall 목록 실패: %s" % ex)
        return
    print("    후보 wall 존 %d개" % len(zones))

    t = TUI()
    si = getattr(getattr(t, "report", None), "surface_integrals", None)
    print("    surface_integrals: %s" % ("있음" if si else "없음"))
    tmp = os.path.join(_HERE, "_c.txt")

    def integ(zone, field, fn_name="area_weighted_avg"):
        fn = getattr(si, fn_name, None) if si else None
        if fn is None:
            return None
        if os.path.exists(tmp):
            os.remove(tmp)
        for args in ((zone, "()", field, "yes", tmp, "yes"),
                     (zone, "()", field, "yes", tmp),
                     (zone, field, "yes", tmp)):
            try:
                fn(*args)
                break
            except Exception:
                continue
        try:
            for line in open(tmp).read().splitlines():
                for tok in line.split()[::-1]:
                    try:
                        return float(tok)
                    except ValueError:
                        continue
        except Exception:
            return None
        return None

    # 첫 존으로 인자 형식을 확인
    if zones:
        v = integ(zones[0], "x-coordinate")
        print("    시험: %s x-coordinate -> %s" % (zones[0], v))

    info = {}
    for z in zones:
        xs = integ(z, "x-coordinate")
        ar = integ(z, "area", "area")
        info[z] = (xs, ar)
        print("      %-44s x %s  area %s" % (z, xs, ar))

    got = [(z, v[0]) for z, v in info.items() if v[0] is not None]
    print("    x 좌표 획득 %d/%d" % (len(got), len(zones)))
    if not got:
        print("    좌표를 못 얻음 — 이름 규칙으로 대체 시도")
        return
    for key, sd in FACE_SEEDS.items():
        best, bd = None, 1e18
        for z, xv in got:
            d = abs(xv * 1000.0 - sd[0])
            if d < bd:
                best, bd = z, d
        print("    %-14s -> %-44s |dx| %.3f mm" % (key, best, bd))
        if best and bd < 1.0:
            try_all("rename %s" % key, [
                ("tui zone-name", lambda b=best, k=key: SOLVER_TUI(
                    "/define/boundary-conditions/modify-zones/"
                    "zone-name %s %s" % (b, k))),
            ])

step("3b. 면 존 각도 분리 (B안)", _separate_faces)
step("3c. 좌표 매칭 + 개명", _match_and_rename)
step("4. 입출구 타입", _zone_types)

def _sym_walls():
    """입출구가 아닌 fluid 자유면을 periodic 으로.

    전체 피치 도메인이므로 y=0↔y=Pt, z=0↔z=Fp 가 translational periodic 임.
    (대칭 1/4 로는 Fluent 이 입구면을 분리해주지 않았고, meshing_utilities 에
     좌표 기반 면존 분리 함수가 없음을 실측 확인 — 그래서 전체 피치로 전환)"""
    S = SETTINGS()
    bc = S.setup.boundary_conditions
    t = TUI()
    try:
        walls = list(bc.wall)
    except Exception as ex:
        print("    wall 목록 실패: %s" % ex)
        return
    print("    wall 존 %d개" % len(walls))
    for w in walls:
        print("      %s" % w)
    # 고체 내부 계면(-solid- 포함)은 conjugate 이므로 건드리지 않음.
    # 바디의 바깥 자유면(':' 로 끝나는 것)만 symmetry 로.
    for w in walls:
        if "-solid-" in w:
            continue
        if "fluid_cell" not in w:
            continue          # 고체 바깥면은 단열 wall 로 둬도 무방
        try_all("%s -> periodic" % w, [
            ("zone_type periodic", lambda ww=w:
                t.define.boundary_conditions.zone_type(ww, "periodic")),
            ("zone_type symmetry", lambda ww=w:
                t.define.boundary_conditions.zone_type(ww, "symmetry"))])
step("5. 대칭면", _sym_walls)

def _bc():
    S = SETTINGS()
    bc = S.setup.boundary_conditions
    for t_ in ("velocity_inlet", "pressure_outlet", "symmetry", "wall"):
        c = getattr(bc, t_, None)
        try:
            print("    %-18s %s" % (t_, str(list(c))[:120] if c else None))
        except Exception as ex:
            print("    %-18s !! %s" % (t_, ex))
    if "cell_inlet" in list(bc.velocity_inlet):
        o = bc.velocity_inlet["cell_inlet"]
        try_all("입구 %.3f m/s / %.1f K" % (V_FACE, T_IN), [
            ("momentum+thermal", lambda: (
                o.momentum.set_state({"velocity_magnitude":
                                      {"option": "value", "value": V_FACE}}),
                o.thermal.set_state({"temperature":
                                     {"option": "value", "value": T_IN}}))[1]),
        ])
    if "cell_outlet" in list(bc.pressure_outlet):
        o = bc.pressure_outlet["cell_outlet"]
        try_all("출구 0 Pa", [
            ("gauge_pressure", lambda: o.momentum.set_state(
                {"gauge_pressure": {"option": "value", "value": 0.0}})),
        ])
step("6. 입출구 조건", _bc)

def _tube_isothermal():
    """관을 등온 고체로 — 냉매측을 풀지 않고 공기측 h 만 뽑기 위함.
       벽 BC 대신 셀 존 fixed_values 를 씀. 관 자유면이 대칭 절단면과
       묶여 있어 벽 BC 로는 대칭면까지 등온이 되기 때문."""
    S = SETTINGS()
    fl = S.setup.cell_zone_conditions.solid
    zones = [z for z in list(fl) if "tube" in z]
    print("    관 존: %s" % zones)
    for z in zones:
        o = fl[z]
        try:
            print("    [스키마] %s" % str(o.get_state())[:220])
        except Exception as ex:
            print("    스키마 실패: %s" % ex)
        try_all("%s 고정온도 %.2f K" % (z, T_WALL), [
            ("fixed_values enable+t", lambda oo=o: oo.fixed_values.set_state(
                {"enable": True,
                 "t": {"option": "value", "value": T_WALL}})),
            ("fixed_values temperature", lambda oo=o: oo.fixed_values.set_state(
                {"enable": True,
                 "temperature": {"option": "value", "value": T_WALL}})),
            ("enable 만", lambda oo=o: oo.fixed_values.set_state({"enable": True})),
        ])
        try:
            print("    [확인] %s" % str(o.fixed_values.get_state())[:220])
        except Exception as ex:
            print("    [확인] 실패: %s" % ex)
step("7. 관 등온 (고정온도)", _tube_isothermal)

step("8. 초기화", lambda: try_all("hybrid", [
    ("settings", lambda: SETTINGS().solution.initialization.hybrid_initialize())]))
step("9. 케이스 저장", lambda: TUI().file.write_case(CASE_OUT))

if ITER > 0:
    step("10. 반복 %d회" % ITER, lambda: try_all("iterate", [
        ("run_calculation",
         lambda: SETTINGS().solution.run_calculation.iterate(iter_count=ITER))]))

    def _results():
        t = TUI()
        si = t.report.surface_integrals
        tmp = os.path.join(_HERE, "_si.txt")
        vals = {}
        for key, fn_name, surf, field in (
                ("p_in",  "area_weighted_avg", "cell_inlet",  "pressure"),
                ("p_out", "area_weighted_avg", "cell_outlet", "pressure"),
                ("t_out", "mass_weighted_avg", "cell_outlet", "temperature"),
        ):
            fn = getattr(si, fn_name, None)
            if fn is None:
                continue
            if os.path.exists(tmp):
                os.remove(tmp)
            for args in ((surf, "()", field, "yes", tmp, "yes"),
                         (surf, "()", field, "yes", tmp)):
                try:
                    fn(*args)
                    break
                except Exception:
                    pass
            try:
                num = None
                for line in open(tmp).read().splitlines():
                    for tok in line.split()[::-1]:
                        try:
                            num = float(tok)
                            break
                        except ValueError:
                            continue
                    if num is not None:
                        break
                vals[key] = num
                print("    %-8s %s" % (key, num))
            except Exception as ex:
                print("    [--] %s: %s" % (key, ex))
        # 벽면 총 열유속
        try:
            fr = t.report.fluxes.heat_transfer
            f2 = os.path.join(_HERE, "_q.txt")
            if os.path.exists(f2):
                os.remove(f2)
            try_all("열유속", [("heat_transfer",
                              lambda: fr("no", "yes", f2, "yes"))])
            for line in open(f2).read().splitlines():
                if "Net" in line or "Total" in line:
                    print("    " + line.strip()[:100])
        except Exception as ex:
            print("    [--] 열유속: %s" % ex)

        out = os.path.join(_HERE, "cell_results.csv")
        cols = ["case", "p_in", "p_out", "t_out", "area_m2", "u_max", "T_in", "T_wall"]
        NL = chr(10)
        with open(out, "w") as fp:
            fp.write(",".join(cols) + NL)
            fp.write(",".join([CASE]
                              + ["" if vals.get(c) is None else "%.6g" % vals[c]
                                 for c in ("p_in", "p_out", "t_out")]
                              + ["%.9g" % AREA, "%.6g" % U_MAX,
                                 "%.6g" % T_IN, "%.6g" % T_WALL]) + NL)
        print("    [OK] cell_results.csv")
    step("11. 결과 추출", _results)
    step("12. 데이터 저장",
         lambda: TUI().file.write_data(CASE_OUT.replace(".cas", ".dat")))

def _verify():
    import time
    print("    저널 폴더: " + _HERE)
    for f in (MESH_IN, CASE_OUT, os.path.join(_HERE, "cell_results.csv")):
        if os.path.exists(f):
            st = os.stat(f)
            print("    [OK] %-24s %8.2f MB  %s" % (
                os.path.basename(f), st.st_size / 1e6,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
        else:
            print("    [!!] %-24s 없음" % os.path.basename(f))
step("13. 파일 확인", _verify)

print("=" * 60)
print("CELL 완료")
print("=" * 60)
try:
    TUI().exit()
except Exception:
    pass
