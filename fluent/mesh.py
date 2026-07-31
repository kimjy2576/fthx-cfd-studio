"""
M1 — 메시 생성기 (Fluent 2025 R1 / PyFluent)

`fthx.meshing.sizing()` 이 유도한 값을 Watertight Geometry 워크플로우에 그대로
주입하고, 품질 게이트를 통과할 때까지 재시도함. 사람이 만질 값이 없음.

    python -m fluent.mesh out/probe_small.step --cores 8
    python -m fluent.mesh out/fthx_face_split_4.step --preset probe --budget 20e6

M0 실측(2025R1)에서 확정한 것들이 기본값으로 들어가 있음:
  · Cells Per Gap = 1   (기본 3 이면 관벽을 틈새로 보고 t/3 까지 세분화)
  · Share Topology = Yes
  · 경계층 없음        (y+ 가 이미 벽함수 범위)
  · Fill = polyhedra

⚠ PyFluent 의 워크플로우 인자 이름은 릴리스마다 바뀜. 이 모듈은 여러 후보를
   순서대로 시도하고 **성공한 경로를 로그와 결과 JSON 에 남김**. 실패해도
   사용 가능한 태스크·인자 목록을 덤프하므로 그 출력으로 고정할 수 있음.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fthx import FTHXParams, meshing, presets  # noqa: E402


# ══════════════════════════════════════════════════════════════════
#  설정
# ══════════════════════════════════════════════════════════════════
@dataclass
class MeshRun:
    step: Path
    params: FTHXParams
    cores: int = 8
    budget: float = 20e6
    min_quality: float = 0.10          # 직교품질 하한
    fill: str = "polyhedra"            # polyhedra | poly-hexcore
    expect_zones: Optional[int] = None  # STEP 바디 수. None → 자동 집계
    out: Optional[Path] = None
    log: list = field(default_factory=list)

    def say(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.log.append(line)


def step_bodies(path: Path) -> list[str]:
    txt = path.read_text(errors="ignore")
    names = re.findall(r"PRODUCT\('([^']+)'", txt)
    return names[1:] if names else []


# ══════════════════════════════════════════════════════════════════
#  버전 차이 흡수
# ══════════════════════════════════════════════════════════════════
def _try(run: MeshRun, label: str, attempts: list[tuple[str, Callable]]):
    errs = []
    for name, fn in attempts:
        try:
            out = fn()
            run.say(f"  ok  {label} ← {name}")
            return name, out
        except Exception as e:                                  # noqa: BLE001
            errs.append(f"{name}: {type(e).__name__}: {str(e)[:150]}")
    run.say(f"  !!  {label} 전부 실패")
    for e in errs:
        run.say(f"      {e}")
    return None, None


def _task(wf, *candidates: str):
    """태스크 이름이 릴리스마다 조금씩 다름 — 후보 중 존재하는 것을 반환."""
    for c in candidates:
        try:
            return wf.TaskObject[c]
        except Exception:                                       # noqa: BLE001
            continue
    raise KeyError(f"태스크 없음: {candidates}")


def _set_args(task, args: dict) -> None:
    for setter in ("set_state", "update_dict"):
        fn = getattr(getattr(task, "Arguments", None), setter, None)
        if fn is not None:
            fn(args)
            return
    task.Arguments = args


# ══════════════════════════════════════════════════════════════════
#  워크플로우
# ══════════════════════════════════════════════════════════════════
def build_mesh(run: MeshRun, ms: Optional[meshing.MeshSpec] = None) -> dict:
    import ansys.fluent.core as pyfluent

    s = meshing.sizing(run.params, ms)
    est = meshing.estimate(run.params, None, ms)
    bodies = step_bodies(run.step)
    expect = run.expect_zones or len(bodies)

    run.say(f"STEP {run.step.name} · 바디 {len(bodies)}개")
    run.say(f"사이징  Min {s['workflow_min_mm']} / Max {s['workflow_max_mm']} / "
            f"Growth {s['growth']} / CellsPerGap {s['surface']['cells_per_gap']}")
    run.say(f"추정    {est['total']/1e6:.2f} M 셀 "
            f"[{est['low']/1e6:.1f}~{est['high']/1e6:.1f}]")

    run.say(f"Fluent 실행 (meshing, {run.cores} core)")
    used, session = _try(run, "launch", [
        ("ui_mode=no_gui", lambda: pyfluent.launch_fluent(
            mode="meshing", precision="double",
            processor_count=run.cores, ui_mode="no_gui")),
        ("show_gui=False", lambda: pyfluent.launch_fluent(
            mode="meshing", precision="double",
            processor_count=run.cores, show_gui=False)),
    ])
    if session is None:
        raise RuntimeError("Fluent 실행 실패")

    api: dict[str, Any] = {"launch": used}
    try:
        try:
            api["fluent"] = str(session.get_fluent_version())
            run.say(f"  {api['fluent']}")
        except Exception:                                       # noqa: BLE001
            pass

        wf = session.workflow
        _try(run, "InitializeWorkflow", [
            ("Watertight Geometry",
             lambda: wf.InitializeWorkflow(WorkflowType="Watertight Geometry"))])

        # ── 1. Import ──────────────────────────────────────────
        run.say("1) Import Geometry")
        t = _task(wf, "Import Geometry")
        _set_args(t, {"FileName": str(run.step.resolve()),
                      "LengthUnit": "mm", "AppendMesh": False})
        t.Execute()

        # ── 2. Local Sizing (관벽에 걸면 안 됨 — 이웃까지 조밀해짐) ──
        run.say("2) Add Local Sizing (건너뜀)")
        try:
            _task(wf, "Add Local Sizing").Execute()
        except Exception as e:                                  # noqa: BLE001
            run.say(f"  건너뜀: {type(e).__name__}")

        # ── 3. Surface Mesh ────────────────────────────────────
        run.say("3) Generate the Surface Mesh")
        t = _task(wf, "Generate the Surface Mesh")
        ctrl = {"MinSize": s["workflow_min_mm"], "MaxSize": s["workflow_max_mm"],
                "GrowthRate": s["growth"],
                "CellsPerGap": s["surface"]["cells_per_gap"],
                "SizeFunctions": "Curvature & Proximity",
                "ScopeProximityTo": "faces"}
        nm, _ = _try(run, "surface args", [
            ("CFDSurfaceMeshControls",
             lambda: _set_args(t, {"CFDSurfaceMeshControls": ctrl})),
            ("flat", lambda: _set_args(t, ctrl))])
        api["surface_args"] = nm
        t.Execute()

        # ── 4. Describe Geometry + Share Topology ──────────────
        run.say("4) Describe Geometry (Share Topology)")
        t = _task(wf, "Describe Geometry", "Geometry Setup")
        _try(run, "describe args", [
            ("full", lambda: _set_args(t, {
                "SetupType": "The geometry consists of both fluid and solid "
                             "regions and/or voids",
                "CappingRequired": "No", "WallToInternal": "No",
                "InvokeShareTopology": "Yes", "NonConformal": "No"})),
            ("minimal", lambda: _set_args(t, {"InvokeShareTopology": "Yes"}))])
        t.Execute()

        for name in ("Apply Share Topology", "Update Boundaries",
                     "Create Regions", "Update Regions"):
            try:
                _task(wf, name).Execute()
                run.say(f"5) {name}")
            except Exception as e:                              # noqa: BLE001
                run.say(f"5) {name} — 생략 ({type(e).__name__})")

        # ── 6. 경계층 제거 (y+ 가 이미 벽함수 범위) ──────────────
        run.say("6) Add Boundary Layers — 비활성")
        for cand in ("Add Boundary Layers", "smooth-transition_1"):
            try:
                bl = _task(wf, cand)
                for m in ("Delete", "DeleteChildren"):
                    if hasattr(bl, m):
                        getattr(bl, m)()
                        break
                else:
                    _set_args(bl, {"BLControlName": "", "AddChild": "no"})
                run.say(f"  {cand} 처리됨")
            except Exception:                                   # noqa: BLE001
                pass

        # ── 7. Volume Mesh ─────────────────────────────────────
        run.say(f"7) Generate the Volume Mesh ({run.fill})")
        t = _task(wf, "Generate the Volume Mesh")
        _try(run, "volume args", [
            ("VolumeFill", lambda: _set_args(t, {
                "VolumeFill": run.fill,
                "VolumeMeshPreferences": {"ShowVolumeMeshPreferences": False}})),
            ("minimal", lambda: _set_args(t, {"VolumeFill": run.fill}))])
        t.Execute()

        # ── 결과 수집 ──────────────────────────────────────────
        stats = collect_stats(run, session)
        stats["api"] = api
        stats["expected_zones"] = expect
        stats["bodies"] = bodies
        stats["sizing"] = s
        stats["estimate"] = {"total": est["total"], "low": est["low"],
                             "high": est["high"]}

        if run.out:
            run.out.parent.mkdir(parents=True, exist_ok=True)
            _try(run, "write mesh", [
                ("tui.file.write_mesh",
                 lambda: session.tui.file.write_mesh(str(run.out))),
                ("meshing.tui.file.write_mesh",
                 lambda: session.meshing.tui.file.write_mesh(str(run.out)))])
            stats["mesh_file"] = str(run.out)
        return stats
    finally:
        try:
            session.exit()
        except Exception:                                       # noqa: BLE001
            pass


def collect_stats(run: MeshRun, session) -> dict:
    """셀 존 수·셀 수·최소 직교품질을 긁어옴."""
    txt = ""
    for path in ("mesh.check_mesh", "meshing.tui.mesh.check_mesh"):
        try:
            obj = session
            for part in path.split("."):
                obj = getattr(obj, part)
            txt = str(obj()) or ""
            break
        except Exception:                                       # noqa: BLE001
            continue
    if not txt:
        try:
            txt = str(session.tui.mesh.check_mesh())
        except Exception:                                       # noqa: BLE001
            txt = ""

    zones = re.findall(r"^\s*(\S+-solid)\s+\d+\s+\d+\s+([\d.]+)\s+(\d+)",
                       txt, re.M)
    total = sum(int(z[2]) for z in zones)
    qmin = min((float(z[1]) for z in zones), default=None)
    if total == 0:
        m = re.search(r"([\d,]+)\s+cells were created", txt)
        if m:
            total = int(m.group(1).replace(",", ""))
    if qmin is None:
        m = re.search(r"minimum Orthogonal Quality of:\s*([\d.]+)", txt)
        qmin = float(m.group(1)) if m else None
    return {"cell_zones": len(zones), "cells": total,
            "min_quality": qmin,
            "per_zone": [{"zone": z[0], "min_quality": float(z[1]),
                          "cells": int(z[2])} for z in zones],
            "raw": txt[-4000:]}


# ══════════════════════════════════════════════════════════════════
#  게이트 + 재시도 사다리
# ══════════════════════════════════════════════════════════════════
LADDER = [
    ("기본", {}),
    ("코어 세분 N_gap 14", {"N_gap": 14}),
    ("전반 세분 N_gap 14 · N_d 16", {"N_gap": 14, "N_d": 16}),
    ("벤드 세분 N_arc 32", {"N_gap": 14, "N_d": 16, "N_arc": 32}),
]


def gate(run: MeshRun, st: dict) -> list[str]:
    bad = []
    if st.get("cell_zones") and st["cell_zones"] != st["expected_zones"]:
        bad.append(f"셀 존 {st['cell_zones']} ≠ STEP 바디 {st['expected_zones']} "
                   "— 임포트 또는 Share Topology 실패 신호")
    q = st.get("min_quality")
    if q is not None and q < run.min_quality:
        bad.append(f"최소 직교품질 {q:.3f} < {run.min_quality}")
    if st.get("cells", 0) > run.budget:
        bad.append(f"셀 {st['cells']:,} > 예산 {run.budget:,.0f}")
    return bad


def run_with_ladder(run: MeshRun) -> dict:
    attempts = []
    for label, over in LADDER:
        run.say(f"── 시도: {label} ──")
        ms = meshing.MeshSpec(**over)
        try:
            st = build_mesh(run, ms)
        except Exception as e:                                  # noqa: BLE001
            run.say(f"  실패: {type(e).__name__}: {e}")
            attempts.append({"step": label, "error": f"{type(e).__name__}: {e}"})
            continue
        issues = gate(run, st)
        attempts.append({"step": label, "cells": st.get("cells"),
                         "zones": st.get("cell_zones"),
                         "min_quality": st.get("min_quality"),
                         "issues": issues})
        if not issues:
            run.say(f"통과 — {st.get('cells'):,} 셀, 품질 {st.get('min_quality')}")
            return {"ok": True, "used": label, "stats": st,
                    "attempts": attempts, "log": run.log}
        for i in issues:
            run.say(f"  게이트 실패: {i}")
        if any("예산" in i for i in issues):
            break                                # 세분화해도 나아지지 않음
    return {"ok": False, "attempts": attempts, "log": run.log}


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", type=Path)
    ap.add_argument("--preset", choices=list(presets.PRESETS),
                    help="형상 파라미터 출처 (미지정 시 기본 케이스)")
    ap.add_argument("--case", type=Path, help="case.json 에서 파라미터 읽기")
    ap.add_argument("--cores", type=int, default=8)
    ap.add_argument("--budget", type=float, default=20e6)
    ap.add_argument("--min-quality", type=float, default=0.10)
    ap.add_argument("--fill", default="polyhedra")
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args()

    if a.case:
        doc = json.loads(a.case.read_text(encoding="utf-8"))
        p = FTHXParams(**{k: v for k, v in doc.items()
                          if k in FTHXParams.model_fields})
    elif a.preset:
        p = presets.PRESETS[a.preset]()
    else:
        p = FTHXParams()

    run = MeshRun(step=a.step, params=p, cores=a.cores, budget=a.budget,
                  min_quality=a.min_quality, fill=a.fill,
                  out=a.out or a.step.with_suffix(".msh.h5"))
    res = run_with_ladder(run)
    rep = a.step.with_suffix(".mesh-report.json")
    rep.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[리포트] {rep}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
