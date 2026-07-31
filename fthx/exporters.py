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

import traceback

STEP        = r"{step_name}"
MESH_OUT    = r"{mesh_out}"
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

def _import():
    t = task("Import Geometry")
    set_args(t, {{"FileName": STEP, "LengthUnit": "mm", "AppendMesh": False}})
    t.Execute()
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
MU = globals().get("meshing_utilities")

def _try_all(label, trials):
    print("  == " + label)
    for name, fn in trials:
        try:
            out = fn()
            if out is False:          # run_menu 는 실패 시 False 를 반환함
                print("    [--] " + name + " -> False (명령 실패)")
                continue
            print("    [OK] " + name + " -> " + str(out)[:300])
            return name, out
        except Exception as e:
            print("    [--] " + name + " : " + type(e).__name__ + ": " + str(e)[:90])
    return None, None

def zone_names(ids):
    nm, out = _try_all("존 id -> 이름", [
        ("convert_zone_ids_to_name_strings(zone_id_list=ids)",
         lambda: MU.convert_zone_ids_to_name_strings(zone_id_list=ids)),
        ("convert_zone_ids_to_name_strings(zone_ids=ids)",
         lambda: MU.convert_zone_ids_to_name_strings(zone_ids=ids)),
    ])
    return out or []

def zone_table():
    """면 존별 id · 이름 · 대표좌표 · 면적. 라벨링의 기초 자료."""
    ids = MU.get_face_zones(filter="*")
    names = zone_names(ids)
    rows = []
    for i, zid in enumerate(ids):
        try:
            c = MU.get_average_bounding_box_center(face_zone_id_list=[zid])
        except Exception:
            c = None
        try:
            a = MU.get_face_zone_area(face_zone_id_list=[zid])
        except Exception:
            a = None
        rows.append({{"id": zid,
                     "name": names[i] if i < len(names) else "?",
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
step("12. 면 존 표 (id/이름/좌표/면적)", _dump_zones)

def _tui_exec():
    """TUI 명령을 문자열로 실행하는 진입점 탐색.

    dir() 로 TUI 트리를 훑는 방식은 신뢰할 수 없음 — getattr 이 존재하지 않는
    이름에도 빈 메뉴를 돌려줌(boundary.improve 가 0개, sep_face_zone_by_angle
    이 호출 불가 메뉴로 나온 이유). 문자열 실행이 되면 문서화된 TUI 명령을
    그대로 쓸 수 있어 탐색이 끝남.
    """
    g = globals()
    for nm in ("run_menu", "cx", "flapi", "PyTUI", "flglobals"):
        o = g.get(nm)
        print("    %-12s %s" % (nm, type(o)))
        if o is None:
            continue
        ns = [n for n in dir(o) if not n.startswith("_")]
        hit = [n for n in ns
               if any(k in n.lower() for k in ("exec", "eval", "menu", "tui",
                                               "scheme", "command", "string"))]
        print("                 관련: %s" % (hit[:14] if hit else "없음"))
    LIST = "/boundary/manage/list"
    SCM = "(ti-menu-load-string " + '"' + LIST + '"' + ")"
    _try_all("TUI 문자열 실행", [
        ("run_menu(LIST)", lambda: g["run_menu"](LIST)),
        ("run_menu(LIST[1:])", lambda: g["run_menu"](LIST[1:])),
        ("cx.eval(SCM)", lambda: g["cx"].eval(SCM)),
        ("flapi.eval(SCM)", lambda: g["flapi"].eval(SCM)),
        ("cx.scheme_eval(SCM)", lambda: g["cx"].scheme_eval(SCM)),
    ])
step("13a. TUI 문자열 실행 진입점", _tui_exec)

def _separate():
    """박스 외벽을 각도로 분리. 문자열 실행이 되면 문서화된 경로를 그대로 씀."""
    g = globals()
    rows = g.get("_ROWS") or []
    targets = [r for r in rows if r["name"] and "interior" not in str(r["name"])
               and str(r["name"]).startswith("fluid_air_")
               and "-solid-" not in str(r["name"])]
    print("    분리 대상 %d개: %s" % (len(targets), [r["name"] for r in targets]))
    rm = g.get("run_menu")
    done = 0
    for r in targets:
        nm = r["name"]
        cands = []
        if rm:
            cands += [
                ("run_menu sep-face-zone-by-angle",
                 lambda nm=nm: rm("/boundary/separate/sep-face-zone-by-angle %s 40 ()"
                                  % nm)),
                ("run_menu separate-face-zone-by-angle",
                 lambda nm=nm: rm("/mesh/modify-zones/separate-face-zone-by-angle "
                                  "%s 40" % nm)),
            ]
        cands.append(("mu.separate_face_zones_by_cell_neighbor",
                      lambda nm=nm: MU.separate_face_zones_by_cell_neighbor(
                          face_zone_name_list=[nm])))
        got, _ = _try_all("분리 %s" % nm, cands)
        if got:
            done += 1
    print("    분리 성공 %d개" % done)
step("13b. 존 각도 분리 (40도)", _separate)

def _match():
    """존 좌표를 face_seeds 와 최근접 매칭."""
    rows = zone_table()
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
step("14. face_seeds 좌표 매칭", _match)

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
            ("tui.boundary.manage.name(old, key)",
             lambda r=r, key=key: TUI().boundary.manage.name(r["name"], key)),
        ])
step("15. 존 이름 부여", _rename)

def _seeds():
    print("    face_seeds %d개" % len(FACE_SEEDS))
    for k in sorted(FACE_SEEDS):
        print("      %-16s %s" % (k, FACE_SEEDS[k]))
step("16. face_seeds 목록", _seeds)

step("17. 라벨된 메시 저장",
     lambda: TUI().file.write_mesh(MESH_OUT.replace(".msh", "_labeled.msh")))

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

## 4) 판정

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
