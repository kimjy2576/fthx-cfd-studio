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

# 각도 분리 단계는 제거함.
# 케이싱 솔리드가 있으면 상·하류 박스의 자유면이 입구/출구만 남아
# 분리가 필요 없음. 남겨두면 32노드 병렬에서 SIGSEGV 를 유발했음(실측).

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

## 5) 판정

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
ITER     = {iterations}

# ── 유도된 값 ──────────────────────────────────────────────
POROSITY  = {a["porosity"]:.6f}
C2        = {a["C2_1perm"]:.4f}          # 1/m, 유동 방향
ALPHA     = {a["alpha_m2"]:.6e}          # m2, 투과율
H_EFF     = {e["h_eff_W_m2K"]:.4f}       # W/m2K (핀효율 반영)
A_V       = {a["a_v_1perm"]:.2f}         # 1/m
HV        = {e["h_eff_W_m2K"] * a["a_v_1perm"]:.2f}   # W/m3K
V_FACE    = {o.air.V_face}               # m/s
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
            ("momentum.velocity", lambda o=obj: o.momentum.set_state(
                 {{"velocity": {{"option": "value", "value": V_FACE}}}})),
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
            ("momentum.mass_flow", lambda o=obj: o.momentum.set_state(
                {{"mass_flow": {{"option": "value",
                               "value": M_REF / N_CIRCUIT}}}})),
        ])
        try_all("냉매 입구 온도 %.1f K" % T_REF, [
            ("thermal.temperature", lambda o=obj: o.thermal.set_state(
                {{"temperature": {{"option": "value", "value": T_REF}}}})),
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
'''
