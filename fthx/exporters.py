"""
해석 패키지 생성 — 서버에 아무것도 설치하지 않고 돌릴 수 있는 묶음.

Fluent Meshing 은 `.py` 저널을 **내장 파이썬**으로 실행함.
즉 PyFluent 설치 없이 워크플로우 API 를 그대로 쓸 수 있음:

    fluent 3d -meshing -g -t8 -i mesh.py

패키지 구성:
    model.step      형상
    case.json       파라미터·회로·존·face_seeds
    mesh.py         Fluent 내장 파이썬 저널 (설치 불필요)
    RUN.md          복붙용 명령 모음 (LSF 클러스터 기준)
    settings.txt    GUI 로 직접 할 때 넣을 값 표
"""
from __future__ import annotations

import json
from typing import Optional

import json

from .params import FTHXParams
from . import meshing


# ══════════════════════════════════════════════════════════════════
#  Fluent 내장 파이썬 저널
# ══════════════════════════════════════════════════════════════════
def fluent_journal(p: FTHXParams, step_name: str = "model.step",
                   mesh_out: str = "mesh.msh.h5",
                   ms: Optional[meshing.MeshSpec] = None,
                   n_bodies: Optional[int] = None,
                   face_seeds: Optional[dict] = None) -> str:
    s = meshing.sizing(p, ms)
    su = s["surface"]
    exp = n_bodies if n_bodies is not None else 0
    seeds = json.dumps(face_seeds or {}, ensure_ascii=False)

    return f'''# -*- coding: utf-8 -*-
# FT-HX CFD Studio — Fluent Meshing 저널 (내장 파이썬)
#
#   fluent 3d -meshing -g -t8 -i mesh.py
#
# 값은 형상에서 유도됨 (fthx.meshing.sizing). 손으로 고칠 것 없음.
#   h_air  = (Pt - Do)/N_gap = {s["h_air_mm"]:.3f} mm
#   h_ref  = Di/N_d          = {s["h_ref_mm"]:.3f} mm
#   h_bend = min(h_ref, pi R/N_arc) = {s["h_bend_mm"]:.3f} mm
#
# Cells Per Gap = {su["cells_per_gap"]} 가 핵심임. 기본 3 이면 관벽({s["wall"]["t_wall_mm"]:.2f}mm)을
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

STEP        = os.path.join(_HERE, r"{step_name}")
MESH_OUT    = os.path.join(_HERE, r"{mesh_out}")
MIN_SIZE    = {su["min_mm"]}
MAX_SIZE    = {su["max_mm"]}
GROWTH      = {su["growth"]}
CELLS_PER_GAP = {su["cells_per_gap"]}
EXPECT_ZONES  = {exp}

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

try_all = _try_all      # 호출부가 두 이름을 섞어 씀


def have(obj, name):
    """속성이 실제로 존재하고 호출 가능한지.

    Fluent 객체는 없는 이름에 None 이나 빈 메뉴를 돌려줌 —
    getattr 결과만 보고 판단하면 'NoneType object is not callable' 로
    한 라운드를 버리게 됨 (실측 반복).
    """
    v = getattr(obj, name, None)
    return v if (v is not None and callable(v)) else None

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
    base = {{"FileName": STEP, "LengthUnit": "mm", "AppendMesh": False}}
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
    ctrl = {{"MinSize": MIN_SIZE, "MaxSize": MAX_SIZE,
            "GrowthRate": GROWTH, "CellsPerGap": CELLS_PER_GAP,
            "SizeFunctions": "Curvature & Proximity",
            "ScopeProximityTo": "faces"}}
    try:
        set_args(t, {{"CFDSurfaceMeshControls": ctrl}})
    except Exception:
        set_args(t, ctrl)
    t.Execute()
step("3. Generate the Surface Mesh", _surface)

def _describe():
    t = task("Describe Geometry", "Geometry Setup")
    try:
        set_args(t, {{
            "SetupType": "The geometry consists of both fluid and solid regions and/or voids",
            "CappingRequired": "No", "WallToInternal": "No",
            "InvokeShareTopology": "Yes", "NonConformal": "No"}})
    except Exception:
        set_args(t, {{"InvokeShareTopology": "Yes"}})
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
        set_args(t, {{"VolumeFill": "polyhedra",
                     "VolumeMeshPreferences": {{"ShowVolumeMeshPreferences": False}}}})
    except Exception:
        set_args(t, {{"VolumeFill": "polyhedra"}})
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
FACE_SEEDS = {seeds}

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
        rows.append({{"id": zid,
                     "name": names[i] if i < len(names) else None,
                     "c": c, "area": a}})
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

# 12b (존 분리) 제거 — 메싱 API 에는 좌표 기반 면존 분리가 없음이
# 실측 확인됨. 분리는 솔버 저널에서 각도 기준으로 수행함(B안).
# 여기서는 메시 생성과 좌표 매칭 기록에만 집중한다.

# 각도 분리 단계는 제거함.
# 케이싱 솔리드가 있으면 상·하류 박스의 자유면이 입구/출구만 남아
# 분리가 필요 없음. 남겨두면 32노드 병렬에서 SIGSEGV 를 유발했음(실측).

def _match():
    """존 좌표를 face_seeds 와 최근접 매칭. rows 가 비어도 죽지 않음."""
    rows = zone_table()
    if not rows:
        print("    면 존 정보 없음 — 매칭 생략")
        globals()["_HITS"] = {{}}
        return
    globals()["_ROWS2"] = rows
    print("    면 존 %d개" % len(rows))
    cand = [r for r in rows if r["c"]]
    hits = {{}}
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
    hits = globals().get("_HITS") or {{}}
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
'''


# ══════════════════════════════════════════════════════════════════
#  실행 안내 (LSF 클러스터)
# ══════════════════════════════════════════════════════════════════
def run_md(p: FTHXParams, ms: Optional[meshing.MeshSpec] = None,
           est: Optional[dict] = None, n_bodies: int = 0) -> str:
    s = meshing.sizing(p, ms)
    su = s["surface"]
    e = est or {}
    tot = e.get("total", 0) / 1e6
    lo = e.get("low", 0) / 1e6
    hi = e.get("high", 0) / 1e6
    return f'''# 실행 방법

Fluent Meshing 은 `.py` 저널을 **내장 파이썬**으로 실행함.
**서버에 아무것도 설치할 필요가 없음.**

## 0) 파일 옮기고 압축 풀기

```bash
cd ~
unzip fthx_case.zip
cd fthx_case
ls          # model.step  mesh.py  case.json  RUN.md  settings.txt
```

## 1) 실행 — 이 블록을 통째로 복사

```bash
cd ~/fthx_case
fluent 3d -meshing -g -t8 -i mesh.py
```

LSF 큐에 제출되고 `Job <번호> is submitted to queue` 가 뜸.
허용 코어 수는 **1 / 2 / 4 / 8 / 32 / 128 / 256 / 512** 중 하나여야 함.

> ⚠ **코어 수가 셀 수에 영향을 줌.** 병렬 분할 경계에서 메시가 달라지기 때문임.
> probe 실측: 4코어 164,461 → 32코어 229,026 (**+39%**).
> 케이스 간 비교를 할 때는 `-t` 값을 반드시 고정할 것.

## 2) 상태 확인

```bash
bjobs                       # PEND=대기, RUN=실행중, 없으면 완료
```

## 3) 결과 확인

```bash
cd ~/fthx_case
ls -lt *.trn *.lsflog | head

# 단계별 성공/실패
grep -E "^(>>>|<<<)" $(ls -t *.trn | head -1)

# 셀 수·품질
grep -E "cells were created|Orthogonal Quality|Total Number of Cell Zones" $(ls -t *.trn | head -1)

# 메시 파일이 저장됐는지
ls -lh mesh.msh.h5

# 오류
grep -iE "error|warning" $(ls -t *.trn | head -1) | head -20
```

## 4) 해석 설정 (M3)

메시가 나온 뒤:

```bash
fluent 3ddp -g -t8 -i setup.py
```

포러스 계수·경계조건·물성이 형상과 운전 조건에서 유도돼 들어감.
`closure.json` 에 그 값들이 정리되어 있음.

## 5) 반복 계산 (M4)

```bash
FTHX_ITER=200 fluent 3ddp -g -t8 -i setup.py
```

`FTHX_ITER` 로 반복 횟수를 정함 (0 이면 설정만). 리포트 정의와 수렴 물리량
출력이 함께 나옴.

> 코어 수는 **코어당 2~5만 셀** 이 적정. probe(285k)는 8~32 코어가 맞고,
> 128 코어는 통신이 계산을 압도해 오히려 느려짐.

## 6) 성능 지표

```bash
python scripts/post_standalone.py examples/<case>
```

`results.csv` + `case.json` + `closure.json` 만 읽어 dP·Q·LMTD·UA·NTU 를 계산함.
**표준 라이브러리만 쓰므로 pip 이 없는 서버에서도 동작**함.
`check.sh` 가 자동으로 호출하므로 따로 칠 필요는 없음.

## 7) 판정

| 항목 | 기대값 |
|---|---|
| 셀 존 수 | **{n_bodies}** (STEP 바디 수와 같아야 함) |
| 셀 수 | 약 {tot:.2f} M (범위 {lo:.2f}~{hi:.2f}) |
| 최소 직교품질 | > 0.10 |

셀 존 수가 다르면 임포트나 Share Topology 가 실패한 것임.

---

## 저널이 쓰는 값

형상에서 유도됨. 손으로 고칠 것 없음.

| | 값 |
|---|---|
| Minimum Size | **{su["min_mm"]}** mm |
| Maximum Size | **{su["max_mm"]}** mm |
| Growth Rate | {su["growth"]} |
| **Cells Per Gap** | **{su["cells_per_gap"]}** |
| Share Topology | Yes |
| 경계층 | 없음 |
| Fill | polyhedra |

`Cells Per Gap` 이 핵심임. 기본값 3 이면 관벽({s["wall"]["t_wall_mm"]:.2f} mm)을 틈새로
인식해 t/3 까지 자동 세분화하고, 셀이 20 배로 늘어남 (2025 R1 실측).

## 저널이 실패하면

각 단계가 `>>> 단계명` / `<<< OK` 또는 `<<< FAIL` 로 로그에 찍힘.
FAIL 이 난 단계와 그 아래 traceback 을 그대로 보내면 고칠 수 있음.
저널은 실패해도 다음 단계로 진행하므로 **한 번 실행으로 모든 문제를 파악**할 수 있음.

## GUI 로 직접 할 때

`settings.txt` 에 넣을 값이 정리되어 있음.
'''


def settings_txt(p: FTHXParams, ms: Optional[meshing.MeshSpec] = None,
                 n_bodies: int = 0) -> str:
    s = meshing.sizing(p, ms)
    su = s["surface"]
    return f'''Watertight Geometry 워크플로우 — 넣을 값
=========================================

1. Import Geometry
     File Name        model.step
     Length Unit      mm
     → Import
     확인: 오브젝트 {n_bodies}개

2. Add Local Sizing
     아무것도 추가하지 않음 → Update
     (관벽에 걸면 안 됨 — 표면이 코어·냉매와 공유되어 이웃까지 조밀해짐)

3. Generate the Surface Mesh          ← 가장 중요
     Minimum Size     {su["min_mm"]}
     Maximum Size     {su["max_mm"]}
     Growth Rate      {su["growth"]}
     Cells Per Gap    {su["cells_per_gap"]}
     → Generate
     ※ 숫자 입력 후 Enter 를 눌러야 확정됨

4. Describe Geometry
     Geometry Type    both fluid and solid regions and/or voids
     Share Topology   Yes
     → Describe

5. Update Boundaries → Create Regions → Update Regions
     기본값 → 각각 Update

6. Add Boundary Layers
     건너뜀 (smooth-transition_* 가 생기면 우클릭 → Delete)

7. Generate the Volume Mesh
     Fill With        polyhedra
     → Generate

확인 명령
---------
     /objects/list
     /boundary/manage/list
     /mesh/check-mesh
   (/mesh/size-info 는 2025 R1 에 없음)
'''


# ══════════════════════════════════════════════════════════════════
#  솔버 저널 (M3 — SETUP)
# ══════════════════════════════════════════════════════════════════
def solver_journal(p: FTHXParams, mesh_in: str = "mesh_labeled.msh.h5",
                   case_out: str = "case.cas.h5",
                   n_circuit: int = 1,
                   iterations: int = 0) -> str:
    """Fluent 솔버 저널. 메싱과 같은 방식으로 내장 파이썬이 실행함:

        fluent 3ddp -g -t32 -i setup.py

    포러스 계수·경계조건·물성은 형상과 운전 조건에서 유도됨. 손으로 넣을 값 없음.
    """
    from . import closure
    c = closure.summary(p, n_circuit)
    a, e, r = c["air"], c["fin"], c["ref"]
    o = p.operating
    air = p.operating_derived()["air"]
    d = p.derived()

    zones = json.dumps({
        "porous": ["fluid_air_core*"],
        "air_fluid": ["fluid_air_up*", "fluid_air_down*", "fluid_air_core*"],
        "ref_fluid": ["fluid_ref*", "fluid_bend*"],
        "solid": ["solid_tube*", "solid_bend*", "solid_casing*"],
    }, ensure_ascii=False)

    return f'''# -*- coding: utf-8 -*-
# FT-HX CFD Studio — Fluent 솔버 저널 (M3 SETUP)
#
#   fluent 3ddp -g -t32 -i setup.py
#
# 값은 형상·운전 조건에서 유도됨 (fthx.closure). 손으로 고칠 것 없음.
#   Re_Dc {a["Re_Dc"]:.0f}  j {a["j"]:.5f}  f {a["f"]:.5f}   ({a["correlation"]})
#   포러스  C2 {a["C2_1perm"]:.1f} 1/m · alpha {a["alpha_m2"]:.3e} m2 · gamma {a["porosity"]:.4f}
#   전열    h {a["h_W_m2K"]:.1f} → eta_o {e["eta_overall"]:.4f} → h_eff {e["h_eff_W_m2K"]:.1f} W/m2K
#           a_v {a["a_v_1perm"]:.0f} 1/m → hv {e["h_eff_W_m2K"] * a["a_v_1perm"]:,.0f} W/m3K
#
# ⚠ 포러스 존은 Fluent 기본이 superficial velocity 임. physical 로 바꾸면
#   ΔP 가 1/gamma^2 배 어긋남. 아래 설정은 superficial 기준임.

import os
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

MESH_IN  = os.path.join(_HERE, r"{mesh_in}")
CASE_OUT = os.path.join(_HERE, r"{case_out}")
ITER     = int(os.environ.get("FTHX_ITER", "{iterations}"))

# ── 유도된 값 ──────────────────────────────────────────────
POROSITY  = {a["porosity"]:.6f}
C2        = {a["C2_1perm"]:.4f}          # 1/m, 유동 방향
ALPHA     = {a["alpha_m2"]:.6e}          # m2, 투과율
H_EFF     = {e["h_eff_W_m2K"]:.4f}       # W/m2K (핀효율 반영)
A_V       = {a["a_v_1perm"]:.2f}         # 1/m
HV        = {e["h_eff_W_m2K"] * a["a_v_1perm"]:.2f}   # W/m3K
V_FACE    = {o.air.V_face}               # m/s
D_H_AIR   = {d["D_h_mm"] / 1000.0:.6f}   # m, 공기측 수력직경
DP_PRED   = {a["dp_core_Pa"]:.4f}        # Pa, closure 가 예측한 코어 압력강하
CASE_NAME = "{p.name}"
T_AIR_IN  = {o.air.T_in + 273.15:.2f}    # K
T_REF     = {o.ref.T_sat_in + 273.15:.2f}  # K
M_REF     = {o.ref.m_total}              # kg/s (전체)
N_CIRCUIT = {n_circuit}
K_TUBE    = {p.tube.k_tube}              # W/mK
THERMAL   = "{o.thermal.model}"
ZONES     = {zones}

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
        # 실측 스키마: porous_zone = {{'porous': False}}, general = {{'laminar': False}}
        try_all("porous 켜기 %s" % n, [
            ("porous_zone.porous = True",
             lambda o=obj: o.porous_zone.set_state({{"porous": True}})),
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
             lambda o=obj: o.general.set_state({{"laminar": True}})),
        ])
        # ⚠ 기본값이 True(=physical velocity). superficial 기준으로 산출한
        #   C2 를 쓰려면 반드시 꺼야 함. 켜두면 dP 가 1/gamma^2 배 어긋남.
        try_all("superficial velocity (relative_velocity_... = False)", [
            ("relative_velocity_resistance_formulation=False",
             lambda o=obj: o.porous_zone.set_state(
                 {{"relative_velocity_resistance_formulation": False}})),
        ])
        try_all("점성 저항 1/alpha = %.4e 1/m2" % (1.0 / ALPHA), [
            ("viscous_resistance direction_1..3",
             lambda o=obj: o.porous_zone.set_state({{"viscous_resistance": {{
                 "direction_1": 1.0 / ALPHA,
                 "direction_2": 1.0 / ALPHA,
                 "direction_3": 1.0 / ALPHA}}}})),
        ])
        try_all("관성 저항 C2 = %.4f 1/m" % C2, [
            ("inertial_resistance direction_1..3",
             lambda o=obj: o.porous_zone.set_state({{"inertial_resistance": {{
                 "option": "constant",
                 "direction_1": C2, "direction_2": C2, "direction_3": C2}}}})),
        ])
        try_all("공극률 %.6f" % POROSITY, [
            ("fluid_porosity option/value",
             lambda o=obj: o.porous_zone.set_state({{"fluid_porosity": {{
                 "option": "constant", "value": POROSITY}}}})),
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
        # 실측 스키마: thermal = {{'temperature': {{'option':'value','value':300}}}}
        try_all("공기 입구 온도 %.1f K" % T_AIR_IN, [
            ("thermal.temperature.value",
             lambda o=obj: o.thermal.set_state(
                 {{"temperature": {{"option": "value", "value": T_AIR_IN}}}})),
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
                 {{"velocity_magnitude": {{"option": "value", "value": V_FACE}}}})),
        ])
        try_all("난류 (I=5%%, 수력직경)", [
            ("turbulence intensity+hydraulic_diameter",
             lambda o=obj: o.turbulence.set_state({{
                 "turbulent_specification": "Intensity and Hydraulic Diameter",
                 "turbulent_intensity": 0.05,
                 "hydraulic_diameter": D_H_AIR}})),
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
                {{"gauge_pressure": {{"option": "value", "value": 0.0}}}})),
        ])
        try_all("출구 역류 온도", [
            ("thermal.temperature", lambda o=obj: o.thermal.set_state(
                {{"temperature": {{"option": "value", "value": T_AIR_IN}}}})),
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
                {{"mass_flow_rate": {{"option": "value",
                                    "value": M_REF / N_CIRCUIT}}}})),
        ])
        try_all("냉매 입구 온도 %.1f K" % T_REF, [
            ("thermal.temperature", lambda o=obj: o.thermal.set_state(
                {{"temperature": {{"option": "value", "value": T_REF}}}})),
        ])
step("6b. 경계조건", _bc)

# ── 7. 열 모델 — 체적 열원 ─────────────────────────────────
# equilibrium: 포러스 코어에 q_vol = hv * (T_ref - T) 를 부과.
#   hv = eta_o * h * a_v  [W/m3K]
#   냉매 등온 가정 — 단상이고 관내 온도변화가 작을 때 성립.
#   관벽 conduction 만으로는 핀 전열이 빠져 UA 가 절반으로 나옴
#   (실측: 열원 없이 UA 2.03 W/K, 예측 전체 UA 4.03 W/K)
def _thermal():
    print("    모드: " + THERMAL)
    if THERMAL == "none":
        print("    단열 — 압력강하만")
        return
    if THERMAL == "netm":
        print("    2온도(NETM) — 고체상↔관벽 접합 미검증. equilibrium 권장")
        return
    print("    hv = eta_o*h*a_v = %.1f W/m3K,  T_ref = %.2f K" % (HV, T_REF))
    S = SETTINGS()
    expr = "%.6g [W m^-3 K^-1] * (%.6g [K] - StaticTemperature)" % (HV, T_REF)
    named = getattr(getattr(S, "setup", None), "named_expressions", None)
    if named is not None:
        try_all("표현식 hx_source", [
            ("create(name=)+set", lambda: (
                named.create(name="hx_source"),
                named["hx_source"].set_state({{"definition": expr}}))[1]),
            ("create(name=,definition=)", lambda: named.create(
                name="hx_source", definition=expr)),
            ("직접 대입", lambda: named.__setitem__(
                "hx_source", {{"definition": expr}})),
        ])
        try:
            print("      정의: %s" % named["hx_source"].get_state())
        except Exception:
            pass
    else:
        print("    named_expressions 없음")
    czc = S.setup.cell_zone_conditions
    fl = czc.fluid
    cores = [n for n in list(fl) if "air_core" in n]
    for n in cores:
        obj = fl[n]
        src = getattr(obj, "sources", None)
        if src is None:
            print("    [--] %s .sources 없음 — 속성: %s" % (
                n, [x for x in dir(obj) if not x.startswith("_")][:20]))
            continue
        try:
            print("    [스키마] %s.sources: %s" % (n, str(src.get_state())[:200]))
        except Exception:
            pass
        # 실측 스키마: sources = {{'energy': {{'nsource': 0}}}}
        # 리스트가 아니라 nsource 로 슬롯 수를 먼저 정하는 구조.
        # 포러스가 porous=True 로 켠 뒤 저항 키가 드러난 것과 같은 패턴.
        # 실측: sources.get_state() 가 TypeError: unhashable type 을 냄.
        #       설정 객체로 소스항을 다루는 경로가 이 버전에서 불안정함.
        #       슬롯도 라운드마다 ['1'] <-> [] 로 바뀜.
        # → TUI 를 주 경로로, 설정 객체는 보조로 둔다.
        EXPR = "hx_source"
        VAL = HV * (T_REF - T_AIR_IN)   # 상수 폴백 [W/m3], 과대평가 주의

        try_all("소스 슬롯 확보 %s" % n, [
            ("nsource=1",
             lambda o=obj: o.sources.set_state({{"energy": {{"nsource": 1}}}})),
            ("energy.nsource 직접",
             lambda o=obj: setattr(o.sources.energy, "nsource", 1)),
        ])
        try:
            print("    슬롯: %s" % list(obj.sources.energy.child_names))
        except Exception as ex:
            print("    슬롯 조회 실패: %s: %s" % (type(ex).__name__, ex))
        try:
            sl = obj.sources.energy["1"]
            print("    slot dir: %s"
                  % [x for x in dir(sl) if not x.startswith("_")][:24])
            try_all("슬롯 값 %s" % n, [
                ("문자열", lambda s2=sl: s2.set_state(EXPR)),
                ("숫자", lambda s2=sl: s2.set_state(VAL)),
                ("value 키", lambda s2=sl: s2.set_state({{"value": VAL}})),
            ])
        except Exception as ex:
            print("    슬롯 접근 불가: %s: %s" % (type(ex).__name__, ex))

        # TUI 폴백 — 설정 객체가 계속 안 맞으면 이쪽
        # TUI 주 경로 — run_menu 로 문자열 실행 (메싱에서 동작 확인됨)
        g = globals()
        rm = g.get("run_menu")
        print("    run_menu: %s" % ("있음" if rm else "없음"))
        if rm:
            # /define/boundary-conditions/fluid <zone> ... 는 인자가 길고
            # 버전마다 달라 되물을 위험이 있음. 대신 존재 확인부터.
            try_all("TUI 존재 확인", [
                ("list-zones", lambda: rm("/define/boundary-conditions/list-zones")),
            ])
        try:
            print("    [확인] %s" % str(obj.sources.get_state())[:220])
        except Exception:
            pass
step("7. 열 모델 (체적 열원)", _thermal)

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
         {{"report_type": "surface-areaavg", "field": "pressure",
          "surface_names": ["air_inlet"]}}),
        ("t_air_out", ["surface"],
         {{"report_type": "surface-massavg", "field": "temperature",
          "surface_names": ["air_outlet"]}}),
        ("m_air_in", ["flux"],
         {{"report_type": "flux-massflow", "zone_names": ["air_inlet"]}}),
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
    vals = {{}}
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
'''



# ══════════════════════════════════════════════════════════════════
#  주기 단위셀 저널 (핀 실형상 → j/f 추출)
# ══════════════════════════════════════════════════════════════════
def cell_mesh_journal(p: FTHXParams, step_name: str = "cell.step",
                      mesh_out: str = "cell.msh.h5",
                      n_bodies: int = 0, face_seeds=None) -> str:
    """단일셀 메시 저널. 풀사이즈와 같은 워크플로우이나 사이징이 다름 —
       z 가 0.9mm 로 얇아 이방성이 필요하므로 Min/Max 를 셀 기준으로 잡음."""
    from . import cell as CELL
    sz = CELL.cell_sizing(p)
    g = CELL.cell_geometry(p)
    ms = meshing.MeshSpec()
    base = fluent_journal(p, step_name, mesh_out, ms, n_bodies, face_seeds)
    # 사이징만 교체 — 간극 반쪽을 nz_gap 분할하는 크기가 하한
    base = base.replace(
        "MIN_SIZE    = %s" % meshing.sizing(p, ms)["workflow_min_mm"],
        "MIN_SIZE    = %.4f" % sz["hz_gap_mm"])
    base = base.replace(
        "MAX_SIZE    = %s" % meshing.sizing(p, ms)["workflow_max_mm"],
        "MAX_SIZE    = %.4f" % sz["h_xy_mm"])
    # cell: 라벨된 메시는 label 단계 산출물 — 메시 저널이 미라벨 사본을
    # 만들면 label 산출물(cell_labeled.msh.h5)을 덮으므로 저장하지 않음.
    base = base.replace(
        'step("16. 라벨된 메시 저장", _write_labeled)',
        'print("16. (건너뜀) 라벨된 메시는 label 단계가 만듦")')
    base = base.replace(
        "    for f in (MESH_OUT, LABELED):",
        "    for f in (MESH_OUT,):")
    return base.replace(
        "# FT-HX CFD Studio — Fluent Meshing 저널 (내장 파이썬)",
        "# FT-HX CFD Studio — 단일셀 Meshing 저널\n"
        "# z 가 %.3fmm 로 얇음. Min %.4f (간극 %d분할) / Max %.4f\n"
        "# 추정 %.0fk 셀"
        % (g["Lz"], sz["hz_gap_mm"], sz["nz_gap"], sz["h_xy_mm"],
           sz["cells_est"] / 1e3))


def cell_label_journal(p: FTHXParams, mesh_in: str = "cell.msh.h5",
                       mesh_out: str = "cell_labeled.msh.h5",
                       face_seeds: Optional[dict] = None) -> str:
    """M2 라벨링 (A안 확정) — 메싱 TUI 각도분리로 입출구 존 분리·개명.

      fluent 3d -meshing -g -t8 -i label.py   (STAGE=label ./go.sh cell 8)

    실측 확정(2580749): /boundary/separate/sep-face-zone-by-angle 은
    존을 **(id) 리스트 문법**으로 줘야 함 — 괄호 없는 id 는 토큰별
    "Invalid entity". 분리 후 기대 면적 조각을 개명. 성공 판정은
    예외가 아니라 **존 수 변화**로 함 (TUI 는 조용히 실패함).
    파이프라인: mesh -> label -> setup -> solve."""
    from . import cell as CELL
    g = CELL.cell_geometry(p)
    inlet_mm2 = g["Ly"] * g["Lz"]

    return f'''# -*- coding: utf-8 -*-
# M2 라벨링 (A안) — 메싱 TUI 각도분리로 입출구 존 분리·개명
#
#   fluent 3d -meshing -g -t8 -i label.py   (STAGE=label ./go.sh cell 8)
#
# 기존 {mesh_in} 을 읽기만 함 — 재메시 불필요. 원본을 덮지 않음.
# 성공 판정: 예외가 아니라 존 수 변화 + 기대 면적({inlet_mm2:.2f} mm2) 존 출현.

import os
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

MESH_IN  = os.path.join(_HERE, r"{mesh_in}")
MESH_OUT = os.path.join(_HERE, r"{mesh_out}")
INLET_AREA_MM2 = {inlet_mm2:.4f}     # 입구 = 전체 단면 Ly x Lz (x=0 엔 핀 없음)
ANGLE    = 40.0                       # 인접 법선차 90도 — 40도면 확실히 갈라짐

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

def _try_all(label, trials):
    print("  == " + label)
    for name, fn in trials:
        try:
            out = fn()
            if out is False or out is None:
                print("    [--] " + name + " -> " + str(out) + " (값 없음)")
                continue
            print("    [OK] " + name + " -> " + str(out)[:200])
            return name, out
        except Exception as e:
            print("    [--] " + name + " : " + type(e).__name__ + ": " + str(e)[:110])
    return None, None

try_all = _try_all

def have(obj, name):
    v = getattr(obj, name, None)
    return v if (v is not None and callable(v)) else None

def _MU():
    g = globals()
    for nm in ("meshing_utilities", "meshing_utilities_app"):
        o = g.get(nm)
        if o is not None:
            return o
    return None

def TUI():
    g = globals()
    for nm in ("PyMenu", "main_menu", "tui"):
        if nm in g and g[nm] is not None:
            return g[nm]
    w = g.get("workflow")
    t = getattr(getattr(w, "_parent", None), "tui", None)
    if t is not None:
        return t
    m = getattr(g.get("meshing"), "tui", None)
    if m is not None:
        return m
    raise NameError("TUI 진입점 없음: " + ", ".join(sorted(
        k for k in g if not k.startswith("_")))[:300])

def TUI_EXEC(cmd):
    g = globals()
    last = None
    for nm in ("meshing", "meshing_app", "session", "root"):
        o = g.get(nm)
        if o is None:
            continue
        for attr in ("execute_tui", "exec_tui", "tui_exec"):
            fn = getattr(o, attr, None)
            if fn is not None:
                try:
                    return fn(cmd)
                except Exception as ex:
                    last = "%s.%s: %s" % (nm, attr, str(ex)[:90])
    raise NameError("execute_tui 경로 없음 (%s)" % last)

# ── 존 조회 (meshing_utilities — 확정 API) ────────────────
def zone_table():
    """[(id, name, area_mm2)] — 면적 단위는 그대로 출력해 실측으로 확정."""
    mu = _MU()
    if mu is None:
        print("    meshing_utilities 없음")
        return []
    ids = mu.get_face_zones(filter="*")
    out = []
    for i in ids:
        try:
            nm = mu.convert_zone_ids_to_name_strings(zone_id_list=[i])
            nm = nm[0] if isinstance(nm, (list, tuple)) and nm else str(nm)
        except Exception:
            nm = "?"
        try:
            ar = mu.get_face_zone_area(face_zone_id_list=[i])
            ar = ar[0] if isinstance(ar, (list, tuple)) and ar else ar
        except Exception:
            ar = None
        out.append((i, nm, ar))
    return out

def dump_zones(tag):
    tz = zone_table()
    print("    [%s] 면 존 %d개" % (tag, len(tz)))
    for i, nm, ar in tz:
        print("      %6s  %-46s area %s" % (i, nm, ar))
    return tz

def near(a, target):
    """면적 단위(mm2/m2)를 모르므로 두 스케일 모두 비교."""
    if a is None:
        return False
    for scale in (1.0, 1e-6):
        t = target * scale
        if t > 0 and abs(a - t) / t < 0.02:
            return True
    return False

step("1. 메시 읽기", lambda: try_all("read-mesh", [
    ("tui file.read_mesh", lambda: TUI().file.read_mesh(MESH_IN)),
    ("exec /file/read-mesh", lambda: TUI_EXEC(
        '/file/read-mesh "%s"' % MESH_IN)),
])[0] or (_ for _ in ()).throw(RuntimeError("메시를 읽지 못함")))

step("2. 분리 전 존 목록", lambda: dump_zones("before"))

def _find_target(prefix):
    """prefix 바디의 자유면 존(가장 큰 것) — 입구가 묶여 있는 그 존."""
    best = None
    for i, nm, ar in zone_table():
        if not nm.startswith(prefix) or "-solid-" in nm[len(prefix):]:
            continue
        if best is None or (ar or 0) > (best[2] or 0):
            best = (i, nm, ar)
    return best

def _already_split():
    for _i, _nm, ar in zone_table():
        if near(ar, INLET_AREA_MM2):
            return _nm
    return None

def _separate(prefix, label):
    """검증된 레시피(2580749): sep-face-zone-by-angle **(id)** ANGLE yes.

    각도분리라 입구 + 측면 4개가 모두 제 존으로 갈라짐 (법선차 90도).
    어느 조각이 입구인지는 면적(기대 46.08 mm2)으로 뒤에서 판정."""
    z = _find_target(prefix)
    if z is None:
        print("    [!!] %s 대상 존 없음" % prefix)
        return
    zid, zname, zarea = z
    print("    대상: id %s  %s  area %s" % (zid, zname, zarea))
    n0 = len(zone_table())
    cmd = "/boundary/separate/sep-face-zone-by-angle (%s) %g yes" % (zid, ANGLE)
    print("      cmd: %s" % cmd)
    TUI_EXEC(cmd)
    n1 = len(zone_table())
    print("      존 수 %d -> %d" % (n0, n1))
    if n1 <= n0:
        raise RuntimeError("%s 분리 실패 — 존 수 불변 (%d)" % (prefix, n0))

def _separations():
    hit = _already_split()
    if hit:
        print("    기대 면적 존이 이미 있음: %s — 분리 생략" % hit)
        return
    _separate("fluid_cell_up",   "입구")
    _separate("fluid_cell_down", "출구")
step("3. 각도분리 (검증된 리스트 문법)", _separations)

def _after():
    tz = dump_zones("after")
    hits = [(i, nm, ar) for i, nm, ar in tz if near(ar, INLET_AREA_MM2)]
    print("    기대 면적(%.2f mm2) 일치 존 %d개: %s"
          % (INLET_AREA_MM2, len(hits), [h[1] for h in hits]))
step("4. 분리 후 존 목록 + 면적 판정", _after)

RENAMED = []

def _rename():
    """면적이 맞는 조각을 바디 이름으로 입/출구 구분해 개명."""
    mu = _MU()
    if mu is None:
        print("    meshing_utilities 없음 — 개명 생략")
        return
    hits = [(i, nm, ar) for i, nm, ar in zone_table()
            if near(ar, INLET_AREA_MM2)]
    if len(hits) != 2:
        print("    [!!] 후보 %d개 (2개여야 함) — 개명 보류, 로그로 판단" % len(hits))
        return
    # up 바디 조각 = 입구(x=0), down 바디 조각 = 출구(x=Lx)
    for i, nm, _ar in hits:
        dst = "cell_inlet" if nm.startswith("fluid_cell_up") else "cell_outlet"
        won, _ = try_all("%s -> %s" % (nm, dst), [
            ("rename_face_zone", lambda a=nm, b=dst:
                mu.rename_face_zone(zone_name=a, new_name=b) or True),
        ])
        if won:
            RENAMED.append(dst)
step("5. 개명", _rename)

def _save():
    """개명 2/2 일 때만 저장. 기존 파일은 먼저 지움 — write_mesh 가
    overwrite 프롬프트에 걸리면 [OK] 를 돌려주고도 실제로는 저장하지
    않음 (실측 2580749: mtime 불변)."""
    if len(RENAMED) != 2:
        raise RuntimeError("개명 %d/2 — 저장 중단" % len(RENAMED))
    if os.path.exists(MESH_OUT):
        os.remove(MESH_OUT)
        print("    기존 %s 삭제 (프롬프트 회피)" % os.path.basename(MESH_OUT))
    try_all("write-mesh", [
        ("tui file.write_mesh", lambda: TUI().file.write_mesh(MESH_OUT)),
        ("exec /file/write-mesh", lambda: TUI_EXEC(
            '/file/write-mesh "%s"' % MESH_OUT)),
    ])
    import time
    st = os.stat(MESH_OUT) if os.path.exists(MESH_OUT) else None
    if st is None or (time.time() - st.st_mtime) > 300:
        raise RuntimeError("저장 검증 실패 — %s 가 새로 쓰이지 않음" % MESH_OUT)
step("6. 저장 (개명 2/2 시에만 · 프롬프트 회피)", _save)

def _verify():
    import time
    for f in (MESH_IN, MESH_OUT):
        if os.path.exists(f):
            st = os.stat(f)
            print("    [OK] %-24s %8.2f MB  %s" % (
                os.path.basename(f), st.st_size / 1e6,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
        else:
            print("    [!!] %-24s 없음" % os.path.basename(f))
step("7. 파일 확인", _verify)

print("=" * 60)
print("LABEL 완료")
print("=" * 60)
try:
    TUI().exit()
except Exception:
    try:
        TUI_EXEC("/exit yes")
    except Exception:
        pass
'''


def cell_journal(p: FTHXParams, mesh_in: str = "cell_labeled.msh.h5",
                 case_out: str = "cell.cas.h5", iterations: int = 0,
                 area_m2: float = 0.0,
                 face_seeds: Optional[dict] = None) -> str:
    """`fluent 3ddp -g -t8 -i cell_setup.py`

    포러스를 쓰지 않음 — 핀이 실형상이므로 소스항 문제와 무관함.
    Re_Dh ~ 500 층류이므로 난류 모델을 켜지 않음.
    """
    from . import cell as CELL
    g = CELL.cell_geometry(p)
    fl = CELL.cell_flow(p)
    sz = CELL.cell_sizing(p)
    if face_seeds is None:
        face_seeds = CELL.build(p)[1]["face_seeds"]
    seeds_json = json.dumps(face_seeds, ensure_ascii=False)

    return f'''# -*- coding: utf-8 -*-
# FT-HX CFD Studio — 주기 단위셀 (핀 실형상)
#
#   fluent 3ddp -g -t8 -i cell_setup.py
#
# 도메인 x {g["Lx"]:.1f} · y {g["Ly"]:.2f} (Pt) · z {g["Lz"]:.3f} (Fp) mm
# 파이프라인: mesh -> label -> setup -> solve.
# 입출구는 label 단계(메싱 TUI 각도분리)가 분리·개명해 둠 —
# 여기서는 확인만 하고, 없으면 B안(솔버 각도분리)으로 폴백.
# 측면은 거울 대칭면(y: 관 중심, z: 핀 사이 중앙) → symmetry
# Re_Dh {fl["Re_Dh"]:.0f} ({fl["regime"]}) → 난류 모델 끔
# 셀 추정 {sz["cells_est"]/1e3:.0f}k · h_xy {sz["h_xy_mm"]} · z {sz["nz_gap"]}+{sz["nz_fin"]}층

import os
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

MESH_IN  = os.path.join(_HERE, r"{mesh_in}")
CASE_OUT = os.path.join(_HERE, r"{case_out}")
ITER     = int(os.environ.get("FTHX_ITER", "{iterations}"))
U_MAX    = {fl["u_max_ms"]:.6f}     # m/s, 최소유동면적 기준
V_FACE   = {fl["V_face_ms"]:.6f}    # m/s, 전면속도 (입구 BC)
T_IN     = {fl["T_in_K"]:.2f}       # K
T_WALL   = {fl["T_wall_K"]:.2f}     # K, 관벽·핀뿌리 등온
AREA     = {area_m2:.9f}            # m2, 공기측 전열면적
LAMINAR  = {str(fl["Re_Dh"] < 2300)}
CASE     = "{p.name}_cell"
FACE_SEEDS = {seeds_json}
# 입구는 슬래브(핀 없음)의 자유면 — 전체 단면 Ly x Lz
INLET_AREA_MM2 = {(g["Ly"] * g["Lz"]):.4f}
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
                o.momentum.set_state({{"velocity_magnitude":
                                      {{"option": "value", "value": V_FACE}}}}),
                o.thermal.set_state({{"temperature":
                                     {{"option": "value", "value": T_IN}}}}))[1]),
        ])
    if "cell_outlet" in list(bc.pressure_outlet):
        o = bc.pressure_outlet["cell_outlet"]
        try_all("출구 0 Pa", [
            ("gauge_pressure", lambda: o.momentum.set_state(
                {{"gauge_pressure": {{"option": "value", "value": 0.0}}}})),
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
                oo.fixed_values.set_state({{"enable": True}}) or True),
        ])
        try:
            st = o.fixed_values.get_state()
        except Exception as ex:
            raise RuntimeError("%s fixed_values 상태 조회 실패: %s" % (z, ex))
        print("    [스키마] %s" % str(st)[:260])
        # 실측 2582504 스키마: {{'enable': True,
        #   'variables': {{'Temperature': {{'option': 'none'}}}}}}
        # 온도 키는 최상위가 아니라 variables 아래, 대문자 Temperature.
        var = st.get("variables", {{}}) if isinstance(st, dict) else {{}}
        tkey = next((k for k in var if "temp" in k.lower()), None)
        if tkey is None:
            raise RuntimeError("%s variables 에 온도 키 없음 — %s"
                               % (z, list(var)))
        try_all("%s variables.%s=%.2f K" % (z, tkey, T_WALL), [
            ("option value", lambda oo=o, k=tkey: oo.fixed_values.set_state(
                {{"variables": {{k: {{"option": "value",
                                     "value": T_WALL}}}}}}) or True),
            ("option constant", lambda oo=o, k=tkey: oo.fixed_values.set_state(
                {{"variables": {{k: {{"option": "constant",
                                     "value": T_WALL}}}}}}) or True),
            ("자식 경로", lambda oo=o, k=tkey:
                oo.fixed_values.variables[k].set_state(
                    {{"option": "value", "value": T_WALL}}) or True),
        ])
        chk = str(o.fixed_values.get_state())
        print("    [확인] %s" % chk[:260])
        if ("%.2f" % T_WALL) not in chk and ("%.1f" % T_WALL) not in chk \
                and str(T_WALL) not in chk:
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
        vals = {{}}
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
'''
