# -*- coding: utf-8 -*-
# FT-HX CFD Studio — Fluent Meshing 저널 (내장 파이썬)
#
#   fluent 3d -meshing -g -t8 -i mesh.py
#
# 값은 형상에서 유도됨 (fthx.meshing.sizing). 손으로 고칠 것 없음.
#   h_air  = (Pt - Do)/N_gap = 1.588 mm
#   h_ref  = Di/N_d          = 0.685 mm
#   h_bend = min(h_ref, pi R/N_arc) = 0.685 mm
#
# Cells Per Gap = 1 가 핵심임. 기본 3 이면 관벽(0.65mm)을
# 틈새로 보고 t/3 까지 자동 세분화해 셀이 20배로 늘어남 (2025R1 실측).
#
# ⚠ 코어 수가 셀 수에 영향을 줌. 병렬 분할 경계에서 메시가 달라지기 때문임.
#   probe 실측: 4코어 164,461 → 32코어 229,026 (+39%).
#   케이스 간 비교를 할 때는 -t 값을 고정할 것.

import os
import traceback

# LSF 로 제출되면 작업 디렉터리가 바뀔 수 있음. 상대 경로로 저장하면
# 엉뚱한 곳에 쓰이고, 폴더에는 이전 실행 파일이 남아 있어 성공한 것처럼 보임
# (실측: 로그는 새 실행인데 mesh.msh.h5 는 3일 전 파일이었음).
# 저널 파일이 있는 폴더를 기준으로 절대 경로를 씀.
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

STEP        = os.path.join(_HERE, r"model.step")
MESH_OUT    = os.path.join(_HERE, r"mesh.msh.h5")
MIN_SIZE    = 0.685
MAX_SIZE    = 3.176
GROWTH      = 1.2
CELLS_PER_GAP = 1
EXPECT_ZONES  = 8

def step(label, fn):
    """각 단계를 감싸 로그에 남김. 실패해도 다음으로 진행해 진단을 모음."""
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

def task(*names):
    for n in names:
        try:
            return workflow.TaskObject[n]
        except Exception:
            continue
    raise KeyError("태스크 없음: " + str(names))

def set_args(t, d):
    try:
        t.Arguments.set_state(d)
    except Exception:
        t.Arguments = d

def TUI():
    """Fluent 내장 파이썬에서 TUI 진입점 이름이 전역이 아닐 수 있음.
       2025R1 실측: 'tui' 는 NameError. 후보를 순서대로 찾음."""
    g = globals()
    for nm in ("tui", "meshing", "solver", "session", "root"):
        o = g.get(nm)
        if o is None:
            continue
        if nm == "tui":
            return o
        t = getattr(o, "tui", None)
        if t is not None:
            return t
    for nm in ("PyMenu", "main_menu"):
        if nm in g:
            return g[nm]
    raise NameError("TUI 진입점을 찾지 못함. globals: "
                    + ", ".join(sorted(k for k in g if not k.startswith("_")))[:400])

# ── 워크플로우 ─────────────────────────────────────────────
step("InitializeWorkflow",
     lambda: workflow.InitializeWorkflow(WorkflowType="Watertight Geometry"))

def _probe_import_api():
    """임포트·존분리 API 를 통째로 덤프. 추측을 멈추고 실제를 본다.

    실측: run_menu 는 메싱에도 없음(NameError). meshing_utilities 는 있음.
    """
    g = globals()
    print("    --- globals (전체) ---")
    ns = sorted(k for k in g if not k.startswith("_"))
    for i in range(0, len(ns), 6):
        print("      " + ", ".join(ns[i:i + 6]))

    print("    --- TUI 문자열 실행 후보 ---")
    LIST = "/boundary/manage/list"
    for label, fn in (
            ("meshing.tui(LIST)", lambda: g["meshing"].tui(LIST)),
            ("meshing.execute_tui(LIST)",
             lambda: g["meshing"].execute_tui(LIST)),
            ("meshing.scheme_eval", lambda: g["meshing"].scheme_eval.scheme_eval(
                "(ti-menu-load-string " + chr(34) + LIST + chr(34) + ")")),
            ("PyTUI", lambda: g["PyTUI"]),
            ("flapi dir", lambda: [x for x in dir(g["flapi"])
                                   if not x.startswith("_")][:20]),
            ("cx dir", lambda: [x for x in dir(g["cx"])
                                if not x.startswith("_")][:20]),
    ):
        try:
            print("      [OK] %-28s %s" % (label, str(fn())[:200]))
        except Exception as ex:
            print("      [--] %-28s %s: %s"
                  % (label, type(ex).__name__, str(ex)[:80]))

    print("    --- tui.file.import_ 하위 ---")
    try:
        imp = TUI().file.import_
        print("      " + ", ".join(x for x in dir(imp)
                                    if not x.startswith("_"))[:400])
    except Exception as ex:
        print("      실패: %s" % ex)

    print("    --- 존 분리 관련 (meshing_utilities) ---")
    mu = g.get("meshing_utilities")
    if mu is not None:
        hits = [x for x in dir(mu) if not x.startswith("_")
                and any(k in x.lower() for k in
                        ("separate", "split", "merge", "rename", "create",
                         "label", "mark"))]
        for i in range(0, len(hits), 3):
            print("      " + ", ".join(hits[i:i + 3]))
step("0. 임포트/분리 API 탐색", _probe_import_api)

def _import():
    """면 단위 존 생성 시도. 실패해도 바디 단위로 진행함."""
    t = task("Import Geometry")
    base = {"FileName": STEP, "LengthUnit": "mm", "AppendMesh": False}
    got, _ = try_all("임포트", [
        ("CreateObjectPer=Face", lambda: (
            set_args(t, dict(base, CreateObjectPer="Face")), t.Execute())[1]),
        ("OneZonePer=Face", lambda: (
            set_args(t, dict(base, OneZonePer="Face")), t.Execute())[1]),
        ("바디 단위", lambda: (set_args(t, base), t.Execute())[1]),
    ])
    print("    임포트 방식: %s" % got)
    try:
        print("    Arguments: %s" % t.Arguments.get_state())
    except Exception as ex:
        print("    Arguments 조회 실패: %s" % ex)
step("1. Import Geometry", _import)

step("2. Add Local Sizing (건너뜀)",
     lambda: task("Add Local Sizing").Execute())

def _surface():
    t = task("Generate the Surface Mesh")
    ctrl = {"MinSize": MIN_SIZE, "MaxSize": MAX_SIZE,
            "GrowthRate": GROWTH, "CellsPerGap": CELLS_PER_GAP,
            "SizeFunctions": "Curvature & Proximity",
            "ScopeProximityTo": "faces"}
    try:
        set_args(t, {"CFDSurfaceMeshControls": ctrl})
    except Exception:
        set_args(t, ctrl)
    t.Execute()
step("3. Generate the Surface Mesh", _surface)

def _describe():
    t = task("Describe Geometry", "Geometry Setup")
    try:
        set_args(t, {
            "SetupType": "The geometry consists of both fluid and solid regions and/or voids",
            "CappingRequired": "No", "WallToInternal": "No",
            "InvokeShareTopology": "Yes", "NonConformal": "No"})
    except Exception:
        set_args(t, {"InvokeShareTopology": "Yes"})
    t.Execute()
step("4. Describe Geometry (Share Topology)", _describe)

for _n in ("Apply Share Topology", "Update Boundaries",
           "Create Regions", "Update Regions"):
    step("5. " + _n, (lambda n: (lambda: task(n).Execute()))(_n))

def _no_bl():
    for c in ("Add Boundary Layers", "smooth-transition_1"):
        try:
            t = task(c)
            for m in ("Delete", "DeleteChildren"):
                if hasattr(t, m):
                    getattr(t, m)()
                    break
        except Exception:
            pass
step("6. Add Boundary Layers 비활성 (y+ 가 이미 벽함수 범위)", _no_bl)

def _volume():
    t = task("Generate the Volume Mesh")
    try:
        set_args(t, {"VolumeFill": "polyhedra",
                     "VolumeMeshPreferences": {"ShowVolumeMeshPreferences": False}})
    except Exception:
        set_args(t, {"VolumeFill": "polyhedra"})
    t.Execute()
step("7. Generate the Volume Mesh", _volume)

# ── 결과 ───────────────────────────────────────────────────
# 8~10 단계: TUI 진입점을 찾아 결과 확인 + 메시 저장
def _check():   TUI().mesh.check_mesh()
def _zones():   TUI().boundary.manage.list()
def _write():   TUI().file.write_mesh(MESH_OUT)

# 저장은 반드시 되어야 하므로 대안 경로도 시도
def _write_any():
    errs = []
    for label, fn in (
            ("TUI().file.write_mesh", _write),
            ("meshing.tui.file.write_mesh",
             lambda: globals()["meshing"].tui.file.write_mesh(MESH_OUT)),
            ("session.tui.file.write_mesh",
             lambda: globals()["session"].tui.file.write_mesh(MESH_OUT)),
            ("workflow parent", lambda: workflow._parent.tui.file.write_mesh(MESH_OUT)),
    ):
        try:
            fn()
            print("    저장 경로: " + label)
            return
        except Exception as e:
            errs.append(label + " -> " + type(e).__name__ + ": " + str(e)[:120])
    print("    !! 메시 저장 실패 — 시도한 경로:")
    for e in errs:
        print("       " + e)
    raise RuntimeError("메시 저장 실패")

step("8. check-mesh", _check)
step("9. boundary list", _zones)
step("10. write mesh", _write_any)

# 전역 이름 덤프 — 위가 실패하면 이 목록으로 경로를 확정할 수 있음
def _dump():
    ns = sorted(k for k in globals() if not k.startswith("_"))
    print("    globals: " + ", ".join(ns))
step("11. 전역 이름 덤프", _dump)

# ── M2 준비: 경계 라벨링 API 탐색 ─────────────────────────
# 목표는 face_seeds 좌표로 면 존을 찾아 이름·타입을 붙이는 것.
# 지금은 바디 단위로 묶여 있을 수 있어(예: fluid_air_up-solid:1 안에
# 입구면과 측벽이 함께) 면 단위 분리가 필요한지 여기서 판정함.
FACE_SEEDS = {"air_inlet": [-40.0, 12.7, 50.0], "air_outlet": [102.0, 12.7, 50.0], "ref_inlet_c01": [11.0, 12.7, 0.0], "ref_outlet_c01": [11.0, 12.7, 100.0]}

# ══════════════════════════════════════════════════════════════
#  M2 — 좌표 기반 경계 라벨링
#
#  M0 에서 계면 존 이름을 신뢰할 수 없음이 확인됐으므로(관벽↔코어가 별도
#  이름 없이 이웃 존에 흡수됨), face_seeds 좌표로 면을 찾아 이름을 붙임.
#
#  확정된 시그니처 (2025R1 실측):
#    mu.get_face_zones(filter="*")                      -> [id, ...]
#    mu.get_cell_zones(filter="*")                      -> [id, ...]
#    mu.get_average_bounding_box_center(face_zone_id_list=[id]) -> [x,y,z]
#    mu.get_face_zone_area(face_zone_id_list=[id])      -> float
#
#  걸림돌: Import Geometry 에 면 단위 존 옵션이 없어 존이 바디 단위로 묶임.
#         → 각도로 분리한 뒤 좌표 매칭.
# ══════════════════════════════════════════════════════════════
def _MU():
    """모듈 로드 시점이 아니라 호출 시점에 찾음.
       (실측: 0단계에서는 있던 이름이 12b 에서 NameError 가 났음)"""
    g = globals()
    for nm in ("meshing_utilities", "meshing_utilities_app"):
        o = g.get(nm)
        if o is not None:
            return o
    return None

MU = _MU()

def _try_all(label, trials):
    print("  == " + label)
    for name, fn in trials:
        try:
            out = fn()
            if out is False or out is None:
                # 실측: convert_zone_ids_to_name_strings 가 None 을 반환하는데
                # [OK] 로 찍혀 이름 없는 _ROWS 가 만들어졌음
                print("    [--] " + name + " -> " + str(out) + " (값 없음)")
                continue
            print("    [OK] " + name + " -> " + str(out)[:300])
            return name, out
        except Exception as e:
            print("    [--] " + name + " : " + type(e).__name__ + ": " + str(e)[:90])
    return None, None

def zone_names(ids):
    """존 id -> 이름. **어떤 경우에도 예외를 내지 않음.**

    실측 회귀: 이 함수가 예외를 던져 zone_table -> _match -> write_mesh 까지
    연쇄로 무너져 메시 파일조차 안 나왔음. 이름은 좌표 매칭에 필수가 아니므로
    실패하면 빈 목록을 돌려주고 진행한다.
    """
    mu = _MU()
    if mu is None:
        return []
    for label, fn in (
            ("zone_id_list=", lambda: mu.convert_zone_ids_to_name_strings(
                zone_id_list=list(ids))),
            ("위치인자", lambda: mu.convert_zone_ids_to_name_strings(
                list(ids))),
    ):
        try:
            out = fn()
        except Exception as ex:
            print("    [--] 이름조회 %s : %s" % (label, str(ex)[:90]))
            continue
        if isinstance(out, (list, tuple)) and out and isinstance(out[0], str):
            print("    [OK] 이름조회 %s" % label)
            return list(out)
        print("    [--] 이름조회 %s -> %s" % (label, str(out)[:60]))
    print("    이름을 못 얻음 — id + 좌표로 진행 (매칭에 이름은 불필요)")
    return []

def zone_table():
    """면 존별 id · 이름 · 대표좌표 · 면적. 실패해도 빈 목록을 돌려줌."""
    mu = _MU()
    if mu is None:
        print("    meshing_utilities 없음")
        return []
    try:
        ids = mu.get_face_zones(filter="*")
    except Exception as ex:
        print("    면 존 조회 실패: %s" % str(ex)[:120])
        return []
    if not ids:
        return []
    names = zone_names(ids)
    rows = []
    for i, zid in enumerate(ids):
        try:
            c = mu.get_average_bounding_box_center(face_zone_id_list=[zid])
        except Exception:
            c = None
        try:
            a = mu.get_face_zone_area(face_zone_id_list=[zid])
        except Exception:
            a = None
        rows.append({"id": zid,
                     "name": names[i] if i < len(names) else None,
                     "c": c, "area": a})
    return rows

def _dump_zones():
    rows = zone_table()
    globals()["_ROWS"] = rows
    print("    면 존 %d개" % len(rows))
    print("    %-8s %-46s %-34s %s" % ("id", "name", "center", "area"))
    for r in rows:
        c = r["c"]
        cs = ("[%9.2f %9.2f %9.2f]" % tuple(c)) if c else "?"
        print("    %-8s %-46s %-34s %s" %
              (r["id"], str(r["name"])[:46], cs,
               ("%.1f" % r["area"]) if r["area"] else "?"))
# 라벨링보다 먼저 저장 — 이후 단계가 깨져도 메시는 보존됨
# (실측 회귀: zone_table 예외로 write_mesh 까지 못 갔음)
step("11b. 메시 선저장", lambda: TUI().file.write_mesh(MESH_OUT))
step("12. 면 존 표 (id/이름/좌표/면적)", _dump_zones)

def TUI_EXEC(cmd):
    """TUI 문자열 실행. 0단계에서 meshing.execute_tui 가 [OK] 였으나
       12b 에서 NameError 가 났음 — 후보를 넓혀 다시 찾음."""
    g = globals()
    last = None
    for nm in ("meshing", "meshing_app", "session", "solver", "root"):
        o = g.get(nm)
        if o is None:
            continue
        for attr in ("execute_tui", "exec_tui", "tui_exec"):
            fn = getattr(o, attr, None)
            if fn is not None:
                try:
                    return fn(cmd)
                except Exception as ex:
                    last = "%s.%s: %s" % (nm, attr, ex)
    raise NameError("execute_tui 경로 없음 (%s) · globals: %s"
                    % (last, ", ".join(sorted(k for k in g
                                              if "mesh" in k.lower()))))

def _sep_api():
    """seed 좌표로 존을 쪼갬. 실패해도 메시는 이미 저장돼 있음(11b).

    실측: separate_face_zones_by_seed() 는 존재하나
          seed_point 라는 인자명은 없음 (unexpected keyword argument).
    """
    mu = _MU()
    if mu is None:
        print("    meshing_utilities 없음")
        return
    globals()["MU"] = mu
    fn = getattr(mu, "separate_face_zones_by_seed", None)
    # 실측 시그니처: face_zone_name_list + seed_points (복수형, list of lists)
    print("    대상 존을 seed 로 분리")
    rows = globals().get("_ROWS") or []
    # 이름을 못 얻는 경우가 있으므로 좌표로도 고를 수 있게 함.
    # 입출구 seed 에 가장 가까운 존이 곧 그 면을 품고 있는 존임.
    def pick(sd):
        best, bd = None, 1e18
        for r in rows:
            c = r.get("c")
            if not c:
                continue
            d = sum((c[i] - sd[i]) ** 2 for i in range(3)) ** 0.5
            if d < bd:
                best, bd = r, d
        return best, bd
    named = [r for r in rows if r.get("name") and "fluid_cell" in str(r["name"])
             and "-solid-" not in str(r["name"])]
    print("      이름으로 고른 대상: %s" % [r["name"] for r in named])
    print("      전체 존 %d개 (이름 있는 것 %d개)"
          % (len(rows), sum(1 for r in rows if r.get("name"))))
    for key in ("cell_inlet", "cell_outlet"):
        sd = FACE_SEEDS.get(key)
        if not sd:
            continue
        cand = named or [pick(sd)[0]] if rows else []
        cand = [c for c in cand if c]
        for r in cand:
            zn = r.get("name")
            if not zn:
                print("      %s: 이름 없음 — id %s 로 시도" % (key, r["id"]))
            got, _ = try_all("%s <- %s seed %s"
                             % (key, zn, [round(v, 2) for v in sd]), [
                ("id_list + seed_points",
                 lambda r=r, sd=sd: mu.separate_face_zones_by_seed(
                     face_zone_id_list=[r["id"]], seed_points=[list(sd)])),
                ("name_list + seed_points",
                 lambda zn=zn, sd=sd: mu.separate_face_zones_by_seed(
                     face_zone_name_list=[zn], seed_points=[list(sd)])),
                ("patterns + seed_points",
                 lambda zn=zn, sd=sd: mu.separate_face_zones_by_seed(
                     face_zone_patterns=[zn], seed_points=[list(sd)])),
                ("id_list + seed_points",
                 lambda r=r, sd=sd: mu.separate_face_zones_by_seed(
                     face_zone_id_list=[r["id"]], seed_points=[list(sd)])),
                ("execute_tui by-seed",
                 lambda zn=zn, sd=sd: TUI_EXEC(
                     "/boundary/separate/sep-face-zone-by-seed %s %g %g %g 40 ()"
                     % (zn, sd[0], sd[1], sd[2]))),
            ])
            if got:
                break
    # 분리 전후를 비교 — 17개였다가 8개로 줄면 뭔가 잘못된 것
    try:
        after = zone_table()
        print("    분리 후 면 존 %d개 (분리 전 %d개)" % (len(after), len(rows)))
        for r in after:
            c = r["c"]
            print("      %-8s %-44s %s  %s" % (
                r["id"], str(r["name"])[:44],
                ("[%8.2f %7.2f %6.3f]" % tuple(c)) if c else "?",
                ("%.1f" % r["area"]) if r["area"] else ""))
        globals()["_ROWS"] = after
    except Exception as ex:
        print("    존 재조회 실패: %s" % ex)
step("12b. seed 기반 존 분리", _sep_api)

# 각도 분리 단계는 제거함.
# 케이싱 솔리드가 있으면 상·하류 박스의 자유면이 입구/출구만 남아
# 분리가 필요 없음. 남겨두면 32노드 병렬에서 SIGSEGV 를 유발했음(실측).

def _match():
    """존 좌표를 face_seeds 와 최근접 매칭. rows 가 비어도 죽지 않음."""
    rows = zone_table()
    if not rows:
        print("    면 존 정보 없음 — 매칭 생략")
        globals()["_HITS"] = {}
        return
    globals()["_ROWS2"] = rows
    print("    면 존 %d개" % len(rows))
    cand = [r for r in rows if r["c"]]
    hits = {}
    for key, seed in FACE_SEEDS.items():
        best, bd = None, 1e18
        for r in cand:
            c = r["c"]
            d = ((c[0]-seed[0])**2 + (c[1]-seed[1])**2 + (c[2]-seed[2])**2) ** 0.5
            if d < bd:
                best, bd = r, d
        hits[key] = (best, bd)
        print("    %-18s -> id %-8s %-40s  거리 %.3f mm" %
              (key, best["id"] if best else "?",
               str(best["name"])[:40] if best else "?", bd))
    bad = [k for k, (r, d) in hits.items() if d > 1.0]
    print("    임계값 1mm 초과: %s" % (bad if bad else "없음"))
    globals()["_HITS"] = hits
step("13. face_seeds 좌표 매칭", _match)

def _rename():
    hits = globals().get("_HITS") or {}
    for key, (r, d) in hits.items():
        if r is None or d > 1.0:
            print("    건너뜀 %s (거리 %.2f)" % (key, d))
            continue
        _try_all("rename %s" % key, [
            ("rename_face_zone(zone_name=old, new_name=key)",
             lambda r=r, key=key: MU.rename_face_zone(
                 zone_name=r["name"], new_name=key)),
            ("rename_face_zone(zone_id=id, new_name=key)",
             lambda r=r, key=key: MU.rename_face_zone(
                 zone_id=r["id"], new_name=key)),
            # TUI 폴백은 두지 않음 — 인자를 되물으면 배치에서 멈춤
        ])
step("14. 존 이름 부여", _rename)

def _seeds():
    print("    face_seeds %d개" % len(FACE_SEEDS))
    for k in sorted(FACE_SEEDS):
        print("      %-16s %s" % (k, FACE_SEEDS[k]))
step("15. face_seeds 목록", _seeds)

LABELED = MESH_OUT.replace(".msh", "_labeled.msh")

def _write_labeled():
    TUI().file.write_mesh(LABELED)

def _verify():
    """저장된 파일을 실제로 확인. 경로·시각·크기를 남겨 이전 실행 파일과
       혼동하지 않게 함 (실측: 로그는 새 실행인데 파일은 옛 것이었음)."""
    import time
    print("    저널 폴더: " + _HERE)
    print("    작업 폴더: " + os.getcwd())
    for f in (MESH_OUT, LABELED):
        if os.path.exists(f):
            st = os.stat(f)
            print("    [OK] %-24s %8.1f MB  %s" %
                  (f, st.st_size / 1e6,
                   time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
        else:
            print("    [!!] %-24s 없음" % f)
    fresh = [f for f in os.listdir(_HERE) if f.endswith(".msh.h5")]
    print("    폴더 내 메시 파일: " + (", ".join(sorted(fresh)) or "없음"))

step("16. 라벨된 메시 저장", _write_labeled)
step("17. 저장 파일 확인", _verify)

print("=" * 60)
print("기대 셀 존 수: " + str(EXPECT_ZONES))
print("위 check-mesh 출력의 Total Number of Cell Zones 와 비교할 것")
print("=" * 60)
