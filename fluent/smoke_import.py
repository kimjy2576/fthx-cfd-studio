#!/usr/bin/env python
"""
M0 스모크 테스트 — STEP 이 Fluent Meshing 에 깨끗히 들어오는지 확인.

확인 항목
---------
1. 바디 수가 STEP 의 PRODUCT 수와 일치하는가
2. 바디 이름(fluid_air_core_r01 …)이 승계되는가
3. per-face granularity 에서 면 존 이름이 어떤 형식으로 붙는가
4. Share Topology 후 포러스↔관벽이 conformal 로 붙는가

사용법
------
    # 1) STEP 생성
    python scripts/gen_case.py --pattern face_split -n 4

    # 2) 임포트 확인 (GUI 없이)
    python fluent/smoke_import.py out/fthx_face_split_4.step

    # 옵션
    python fluent/smoke_import.py FILE --cores 8 --granularity body --gui

주의
----
Fluent 버전마다 PyFluent API 이름이 바뀜. 이 스크립트는 여러 경로를 순서대로
시도하고 **어느 것이 동작했는지 로그에 남김**. 실패해도 사용 가능한 API 목록을
덤프하므로, 그 출력을 그대로 보내주면 버전에 맞춰 고정할 수 있음.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# ──────────────────────────────────────────────────────────────
#  STEP 쪽 기준값 (Fluent 결과와 비교할 대조군)
# ──────────────────────────────────────────────────────────────
def step_products(path: Path) -> list[str]:
    txt = path.read_text(errors="ignore")
    names = re.findall(r"PRODUCT\('([^']+)'", txt)
    root = names[0] if names else None
    return [n for n in names if n != root]


def summarize(names: list[str]) -> dict:
    groups: dict[str, int] = {}
    for n in names:
        key = re.sub(r"(_r\d+t\d+|_r\d+|_c\d+_k\d+|_c\d+)$", "", n)
        groups[key] = groups.get(key, 0) + 1
    return dict(sorted(groups.items()))


# ──────────────────────────────────────────────────────────────
#  Fluent
# ──────────────────────────────────────────────────────────────
def try_all(label: str, attempts: list[tuple[str, callable]]) -> tuple[str | None, object]:
    """여러 API 경로를 순서대로 시도하고 성공한 이름을 돌려줌."""
    errs = []
    for name, fn in attempts:
        try:
            out = fn()
            print(f"    [OK] {label}: {name}")
            return name, out
        except Exception as e:                       # noqa: BLE001
            errs.append(f"      · {name} → {type(e).__name__}: {str(e)[:120]}")
    print(f"    [!!] {label}: 전부 실패")
    print("\n".join(errs))
    return None, None


def run(step: Path, cores: int, granularity: str, gui: bool) -> int:
    print("=" * 68)
    print(f"STEP: {step}  ({step.stat().st_size/1e6:.2f} MB)")
    prods = step_products(step)
    print(f"STEP PRODUCT (루트 제외) = {len(prods)} 개")
    for k, v in summarize(prods).items():
        print(f"    {k:<28}{v:>4}")
    print("=" * 68)

    try:
        import ansys.fluent.core as pyfluent
    except ImportError:
        print("\n[오류] ansys-fluent-core 가 없음:")
        print("    pip install ansys-fluent-core")
        print("  또는 GUI 로 확인 (fluent/README.md 참고)")
        return 2

    print(f"\nPyFluent {getattr(pyfluent, '__version__', '?')} · Fluent 실행 중…")
    launch = [
        ("ui_mode",
         lambda: pyfluent.launch_fluent(mode="meshing", precision="double",
                                        processor_count=cores,
                                        ui_mode="gui" if gui else "no_gui")),
        ("show_gui",
         lambda: pyfluent.launch_fluent(mode="meshing", precision="double",
                                        processor_count=cores, show_gui=gui)),
        ("minimal",
         lambda: pyfluent.launch_fluent(mode="meshing")),
    ]
    used, session = try_all("launch_fluent", launch)
    if session is None:
        return 3

    info: dict = {"launch_api": used, "step_products": len(prods),
                  "pyfluent": getattr(pyfluent, "__version__", None)}
    try:
        try:
            print(f"    Fluent build: {session.get_fluent_version()}")
            info["fluent_version"] = str(session.get_fluent_version())
        except Exception:
            pass

        # ---- Watertight 워크플로우 초기화 ----
        wf = getattr(session, "workflow", None) or getattr(session, "meshing", None)
        try_all("InitializeWorkflow", [
            ("workflow.InitializeWorkflow",
             lambda: wf.InitializeWorkflow(WorkflowType="Watertight Geometry")),
        ])

        # ---- 임포트 ----
        args = {"FileName": str(step.resolve()), "LengthUnit": "mm",
                "AppendMesh": False}
        if granularity == "face":
            args["CreateObjectPer"] = "Face"
        elif granularity == "body":
            args["CreateObjectPer"] = "Body"

        def _wf_import():
            t = wf.TaskObject["Import Geometry"]
            t.Arguments.set_state(args) if hasattr(t.Arguments, "set_state") \
                else t.Arguments.update_dict(args)
            t.Execute()
            return t

        try_all("Import Geometry", [
            ("workflow.TaskObject['Import Geometry']", _wf_import),
            ("tui.file.import_.cad_geometry",
             lambda: session.tui.file.import_.cad_geometry(str(step.resolve()))),
            ("tui.file.import_.cad",
             lambda: session.tui.file.import_.cad(str(step.resolve()))),
        ])

        # ---- 오브젝트/존 목록 ----
        def _objects():
            return session.scheme_eval.scheme_eval(
                '(map (lambda (o) (send o :id)) (get-all-object-refs))')

        nm, objs = try_all("오브젝트 목록", [
            ("tui.objects.list", lambda: session.tui.objects.list()),
            ("scheme: inquire-objects",
             lambda: session.scheme_eval.scheme_eval("(inquire-objects)")),
            ("scheme: object refs", _objects),
        ])
        if objs is not None:
            print("\n---- 오브젝트 목록 (앞 40줄) ----")
            txt = objs if isinstance(objs, str) else str(objs)
            for line in txt.splitlines()[:40]:
                print("   ", line)
            info["objects_api"] = nm

        nm, zones = try_all("면 존 목록", [
            ("tui.boundary.manage.list", lambda: session.tui.boundary.manage.list()),
            ("scheme: face zones",
             lambda: session.scheme_eval.scheme_eval(
                 '(map (lambda (z) (zone-name z)) (inquire-face-zones))')),
        ])
        if zones is not None:
            print("\n---- 면 존 이름 (앞 40개) ----")
            txt = zones if isinstance(zones, str) else str(zones)
            for line in txt.splitlines()[:40]:
                print("   ", line)
            info["face_zone_api"] = nm

        out = step.with_suffix(".fluent-probe.json")
        out.write_text(json.dumps(info, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"\n[저장] {out}")
        print("\n※ 이 출력 전체를 보내주면 버전에 맞춰 API 를 고정할 수 있음.")
    finally:
        try:
            session.exit()
        except Exception:
            pass
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", type=Path)
    ap.add_argument("--cores", type=int, default=4)
    ap.add_argument("--granularity", choices=["face", "body", "auto"],
                    default="face",
                    help="face = B-rep 면마다 존 생성 (좌표 라벨링에 필요)")
    ap.add_argument("--gui", action="store_true")
    a = ap.parse_args()
    if not a.step.exists():
        print(f"[오류] 파일 없음: {a.step}")
        return 1
    return run(a.step, a.cores, a.granularity, a.gui)


if __name__ == "__main__":
    sys.exit(main())
