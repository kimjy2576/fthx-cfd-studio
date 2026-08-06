# -*- coding: utf-8 -*-
# FT-HX CFD Studio — 주기 단위셀 (핀 실형상)
#
#   fluent 3ddp -g -t8 -i cell_setup.py
#
# 도메인 x 176.0 · y 25.40 (Pt) · z 1.814 (Fp) mm
# 파이프라인: mesh -> label -> setup -> solve.
# 입출구는 label 단계(메싱 TUI 각도분리)가 분리·개명해 둠 —
# 여기서는 확인만 하고, 없으면 B안(솔버 각도분리)으로 폴백.
# 측면은 거울 대칭면(y: 관 중심, z: 핀 사이 중앙) → symmetry
# Re_Dh 489 (laminar) → 난류 모델 끔
# 셀 추정 1502k · h_xy 0.25 · z 10+2층

import os
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

MESH_IN  = os.path.join(_HERE, r"cell_labeled.msh.h5")
CASE_OUT = os.path.join(_HERE, r"cell.cas.h5")
ITER     = int(os.environ.get("FTHX_ITER", "0") or 0)
if ITER == 0:
    # env 는 이 클러스터의 fluent 래퍼 LSF 잡까지 닿지 않음 (실측 2582515)
    # — go.sh 가 solve 스테이지에서 _iter 파일로 전달함
    _itf = os.path.join(_HERE, "_iter")
    if os.path.exists(_itf):
        try:
            ITER = int(open(_itf).read().strip() or 0)
        except Exception:
            ITER = 0
if ITER == 0:
    ITER = int("0")
print("ITER = %d  (env %r / _iter %s)" % (
    ITER, os.environ.get("FTHX_ITER"),
    "있음" if os.path.exists(os.path.join(_HERE, "_iter")) else "없음"))
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
ANGLE = 40.0     # B안 폴백용 — 인접 법선차 90도

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

def _io_area(zone):
    """조각 면적 (mm2/m2 불문) — 실측 2580752 에서 작동 확인된 TUI 체인."""
    t = TUI()
    si = getattr(getattr(t, "report", None), "surface_integrals", None)
    fn = getattr(si, "area", None) if si else None
    if fn is None:
        return None
    tmp = os.path.join(_HERE, "_a.txt")
    if os.path.exists(tmp):
        os.remove(tmp)
    for args in ((zone, "()", "yes", tmp, "yes"),
                 (zone, "()", "yes", tmp),
                 (zone, "yes", tmp)):
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

def _io_match(a):
    if a is None:
        return False
    for sc in (1.0, 1e-6):
        t_ = INLET_AREA_MM2 * sc
        if abs(a - t_) / t_ < 0.02:
            return True
    return False

def _ensure_io():
    """입출구 확보 — 원칙은 label 단계 산출물 확인만.

    cell_inlet/cell_outlet 이 없으면 B안 폴백: 솔버 각도분리
    sep_face_zone_angle ("by" 없는 정식명 — 실측 2580752 에서
    wall 19->23->27 검증) 후 면적으로 조각을 찾아 개명."""
    t = TUI()
    plain, _sh = _walls()
    if "cell_inlet" in plain and "cell_outlet" in plain:
        print("    라벨 확인: cell_inlet / cell_outlet 있음 (label 단계 산출물)")
        return
    print("    [!!] 라벨 없음 — B안 폴백 (라벨 안 된 메시를 읽었을 때)")
    mz = getattr(getattr(t, "mesh", None), "modify_zones", None)
    if mz is None:
        raise RuntimeError("mesh.modify_zones 없음 — label 단계를 먼저 돌릴 것")
    for src, dst in (("fluid_cell_up-solid:1", "cell_inlet"),
                     ("fluid_cell_down-solid:1", "cell_outlet")):
        n0 = len(_walls()[0])
        mz.sep_face_zone_angle(src, ANGLE)
        pieces = [w for w in _walls()[0]
                  if w.startswith(src + ":") or w == src]
        print("    %s 분리: wall %d -> %d, 조각 %s"
              % (src, n0, len(_walls()[0]), pieces))
        hit = [w for w in pieces if _io_match(_io_area(w))]
        if len(hit) != 1:
            raise RuntimeError("%s 조각 중 기대 면적 일치 %d개" % (src, len(hit)))
        try_all("%s -> %s" % (hit[0], dst), [
            ("mesh.modify_zones.zone_name", lambda a=hit[0], b=dst:
                mz.zone_name(a, b)),
            ("bc.modify_zones.zone_name", lambda a=hit[0], b=dst:
                t.define.boundary_conditions.modify_zones.zone_name(a, b)),
        ])
step("3d. 입출구 확보 (라벨 확인 · 없으면 B안 폴백)", _ensure_io)

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
    import re
    t = TUI()
    plain, shadows = _walls()
    for w in plain:
        # 계면 이름은 A-solid-B-solid 꼴 — "-solid-" 뒤에 다음 바디의
        # fluid_/solid_ 접두가 옴. 단순 "-solid-" 포함 검사는
        # fluid_cell_core-solid-2-:1 (코어 위쪽 공기 자유면)까지 계면으로
        # 오인해 벽으로 남김 (실측 2582504 — 대칭 9/10).
        if re.search(r"-solid-(?:fluid_|solid_)", w) or "fluid_cell" not in w:
            continue
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
       벽 BC 대신 셀 존 fixed_values 를 씀.

       실측 2582491: 't'/'temperature' 키가 KeyError — 키 이름을 추측하지
       말고 enable 후 get_state 로 **실제 키를 읽어** 그 키에 값을 넣음.
       설정 후 재조회로 T_WALL 반영을 검증 — 안 되면 raise (조용한 실패
       금지: 관이 등온이 아니면 결과 전체가 무의미함)."""
    S = SETTINGS()
    fl = S.setup.cell_zone_conditions.solid
    zones = [z for z in list(fl) if "tube" in z]
    print("    관 존: %s" % zones)
    for z in zones:
        o = fl[z]
        try_all("%s fixed enable" % z, [
            ("fixed_values enable", lambda oo=o:
                oo.fixed_values.set_state({"enable": True}) or True),
        ])
        try:
            st = o.fixed_values.get_state()
        except Exception as ex:
            raise RuntimeError("%s fixed_values 상태 조회 실패: %s" % (z, ex))
        print("    [스키마] %s" % str(st)[:260])
        # 실측 2582504 스키마: {'enable': True,
        #   'variables': {'Temperature': {'option': 'none'}}}
        # 온도 키는 최상위가 아니라 variables 아래, 대문자 Temperature.
        var = st.get("variables", {}) if isinstance(st, dict) else {}
        tkey = next((k for k in var if "temp" in k.lower()), None)
        if tkey is None:
            raise RuntimeError("%s variables 에 온도 키 없음 — %s"
                               % (z, list(var)))
        try_all("%s variables.%s=%.2f K" % (z, tkey, T_WALL), [
            ("option value", lambda oo=o, k=tkey: oo.fixed_values.set_state(
                {"variables": {k: {"option": "value",
                                     "value": T_WALL}}}) or True),
            ("option constant", lambda oo=o, k=tkey: oo.fixed_values.set_state(
                {"variables": {k: {"option": "constant",
                                     "value": T_WALL}}}) or True),
            ("자식 경로", lambda oo=o, k=tkey:
                oo.fixed_values.variables[k].set_state(
                    {"option": "value", "value": T_WALL}) or True),
        ])
        chk = str(o.fixed_values.get_state())
        print("    [확인] %s" % chk[:260])
        if ("%.2f" % T_WALL) not in chk and ("%.1f" % T_WALL) not in chk                 and str(T_WALL) not in chk:
            raise RuntimeError("%s 온도 %.2f K 미반영 — 상태: %s"
                               % (z, T_WALL, chk[:200]))
step("7. 관 등온 (고정온도)", _tube_isothermal)

step("8. 초기화", lambda: try_all("hybrid", [
    ("settings", lambda: SETTINGS().solution.initialization.hybrid_initialize())]))
def _save_case():
    """저장을 시끄럽게 — write_mesh 와 같은 부류의 조용한 실패 차단.
       (실측 2582491: 9단계 [OK] 인데 cell.cas.h5 부재)"""
    if os.path.exists(CASE_OUT):
        os.remove(CASE_OUT)
        print("    기존 %s 삭제 (프롬프트 회피)" % os.path.basename(CASE_OUT))
    try_all("write-case", [
        ("tui write_case", lambda: TUI().file.write_case(CASE_OUT) or True),
        ("tui write_case yes", lambda:
            TUI().file.write_case(CASE_OUT, "yes") or True),
        ("settings file.write", lambda: SETTINGS().file.write(
            file_name=CASE_OUT, file_type="case") or True),
    ])
    import time
    if not os.path.exists(CASE_OUT):
        raise RuntimeError("케이스 저장 실패 — %s 없음" % CASE_OUT)
    st = os.stat(CASE_OUT)
    print("    [OK] %s  %.1f MB  %s" % (
        os.path.basename(CASE_OUT), st.st_size / 1e6,
        time.strftime("%H:%M:%S", time.localtime(st.st_mtime))))
step("9. 케이스 저장 (검증 포함)", _save_case)

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
