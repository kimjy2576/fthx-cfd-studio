# -*- coding: utf-8 -*-
# FT-HX CFD Studio — 주기 단위셀 (핀 실형상)
#
#   fluent 3ddp -g -t8 -i cell_setup.py
#
# 도메인 x 176.0 · y 25.40 (Pt) · z 1.814 (Fp) mm
# C안: 끝단 슬래브(2.0mm) 측면을 케이싱으로 감쌈 —
#      슬래브 자유면 = 입구/출구 뿐이라 존이 저절로 분리됨.
# 측면은 거울 대칭면(y: 관 중심, z: 핀 사이 중앙) → symmetry
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
# 입구는 슬래브(핀 없음)의 자유면 — 전체 단면 Ly x Lz
INLET_AREA_MM2 = 46.0829
INLET_SRC  = "fluid_cell_slab_in-solid"    # C안: 이 바디의 유일한 자유면 = 입구
OUTLET_SRC = "fluid_cell_slab_out-solid"

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

def _walls():
    """shadow 짝이 있는 존은 conjugate 벽 — 목록과 함께 돌려줌."""
    S = SETTINGS()
    bc = S.setup.boundary_conditions
    walls = list(bc.wall)
    shadows = set(w for w in walls if w.endswith("-shadow"))
    plain = [w for w in walls if not w.endswith("-shadow")]
    return plain, shadows

def _zone_survey():
    """타입별 존 목록 — 진단용."""
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
step("3b. 존 조사", _zone_survey)

def _air_air_interior():
    """공기-공기 계면을 interior 로.

    실측(2578722): fluid_cell_core-solid-fluid_cell_up-solid 등이
    wall(+shadow) 로 들어와 있었음 — 이대로면 상류→코어 유동이 막힘.
    이름에 fluid_cell 이 두 번 나오는 벽이 공기-공기 계면임.
    (solid_cap 계면·핀 계면은 conjugate 벽으로 남겨야 하므로 제외됨)"""
    t = TUI()
    plain, _ = _walls()
    tgt = [w for w in plain if w.count("fluid_cell") >= 2]
    print("    공기-공기 계면 %d개" % len(tgt))
    for w in tgt:
        try_all("%s -> interior" % w, [
            ("zone_type interior", lambda ww=w:
                t.define.boundary_conditions.zone_type(ww, "interior")),
            ("modify_zones.zone_type", lambda ww=w:
                t.define.boundary_conditions.modify_zones.zone_type(
                    ww, "interior")),
        ])
step("3c. 공기-공기 계면 -> interior", _air_air_interior)

def _rename_io():
    """입출구 개명 — C안: 슬래브 바디의 유일한 자유면이 곧 입구(출구).

    좌표·면적 조회가 전혀 필요 없음. 슬래브 측면은 케이싱과의 conjugate
    벽(shadow 짝 있음), 흐름 방향 면은 공기-공기 계면(위에서 interior)이므로
    남는 자유면 벽은 정확히 하나임. (형상 회귀 테스트로 고정됨)"""
    t = TUI()
    plain, shadows = _walls()
    print("    입구면 기대 면적 %.2f mm2 (검산용)" % INLET_AREA_MM2)
    for src, dst in ((INLET_SRC, "cell_inlet"), (OUTLET_SRC, "cell_outlet")):
        cand = [w for w in plain
                if w.startswith(src)                    # 해당 슬래브 바디의 존
                and "-solid-" not in w[len(src):]       # 계면 제외
                and (w + "-shadow") not in shadows]     # conjugate 벽 제외
        print("    %s 후보: %s" % (dst, cand))
        if len(cand) != 1:
            print("    [!!] 후보가 %d개 — 개명 보류. 존 조사(3b) 출력 확인 요망"
                  % len(cand))
            continue
        try_all("%s -> %s" % (cand[0], dst), [
            ("modify_zones.zone_name", lambda a=cand[0], b=dst:
                t.define.boundary_conditions.modify_zones.zone_name(a, b)),
            ("zone_name", lambda a=cand[0], b=dst:
                t.define.boundary_conditions.zone_name(a, b)),
        ])
step("3d. 입출구 개명 (슬래브 자유면)", _rename_io)

def _zone_types():
    """메싱에서 이름만 바뀐 존은 솔버에서 전부 wall — 타입을 바꿔야 BC 가 걸림.
       (실측 2578722: 이 함수가 정의 없이 호출돼 저널이 3c 에서 죽었음 —
        헬퍼는 반드시 첫 호출보다 앞에. 회귀 테스트로 고정됨)"""
    t = TUI()
    for zone, typ in (("cell_inlet", "velocity-inlet"),
                      ("cell_outlet", "pressure-outlet")):
        try_all("%s -> %s" % (zone, typ), [
            ("define.boundary_conditions.zone_type",
             lambda z=zone, y=typ: t.define.boundary_conditions.zone_type(z, y)),
            ("modify_zones.zone_type",
             lambda z=zone, y=typ:
                 t.define.boundary_conditions.modify_zones.zone_type(z, y)),
        ])
step("4. 입출구 타입", _zone_types)

def _sym_walls():
    """남은 fluid 자유면(측면)을 symmetry 로.

    y=0/Pt 는 관 중심을 지나는 거울면(staggered 도 성립),
    z=0/Fp 는 핀 사이 중앙 거울면 — 기하적으로 정확한 대칭이므로
    짝 맞춤이 필요한 periodic 대신 symmetry 를 씀.
    conjugate 벽(shadow 짝 있음 — 핀 전연·케이싱 계면)은 제외."""
    t = TUI()
    plain, shadows = _walls()
    for w in plain:
        if "-solid-" in w or "fluid_cell" not in w:
            continue                      # 고체 자유면은 단열 wall 로 둠
        if w in ("cell_inlet", "cell_outlet"):
            continue
        if (w + "-shadow") in shadows:
            continue                      # conjugate 벽 (핀 전연 등)
        try_all("%s -> symmetry" % w, [
            ("zone_type symmetry", lambda ww=w:
                t.define.boundary_conditions.zone_type(ww, "symmetry")),
            ("modify_zones.zone_type", lambda ww=w:
                t.define.boundary_conditions.modify_zones.zone_type(
                    ww, "symmetry")),
        ])
step("5. 측면 대칭면", _sym_walls)

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
