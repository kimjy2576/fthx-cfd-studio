#!/usr/bin/env python
"""examples/cell 재생성 — STEP + case.json + mesh.py + setup.py.

  python scripts/gen_cell.py

클러스터에는 CadQuery 가 없으므로 STEP 은 로컬에서 생성해 커밋함.
형상(fthx/cell.py)이 바뀌면 반드시 이 스크립트로 재생성할 것 —
저널만 갱신하고 STEP 을 안 바꾸면 이전 형상으로 메시가 만들어짐.
"""
import ast
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fthx import cell, exporters, presets  # noqa: E402

OUT = ROOT / "examples" / "cell"
p = presets.cell()

# ── STEP + 메타 ────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    meta = cell.export(p, outdir=td)
    shutil.copy(meta["_files"]["step"], OUT / "cell.step")
    shutil.copy(meta["_files"]["json"], OUT / "case.json")

n_bodies = len(meta["tube_centers"]) + 3 + 1   # 관 + 공기3 + 핀
area = cell.heat_area_m2(p)
seeds = meta["face_seeds"]

# ── 저널 ───────────────────────────────────────────────────
jm = exporters.cell_mesh_journal(p, step_name="cell.step",
                                 mesh_out="cell.msh.h5",
                                 n_bodies=n_bodies, face_seeds=seeds)
js = exporters.cell_journal(p, mesh_in="cell_labeled.msh.h5",
                            case_out="cell.cas.h5",
                            area_m2=area, face_seeds=seeds)
jl = exporters.cell_label_journal(p, mesh_in="cell.msh.h5",
                                  mesh_out="cell_labeled.msh.h5",
                                  face_seeds=seeds)
ast.parse(jm)      # f-string 이스케이프 실수는 여기서 잡힘 (하지 말 것 #8)
ast.parse(js)
ast.parse(jl)
(OUT / "mesh.py").write_text(jm, encoding="utf-8")
(OUT / "setup.py").write_text(js, encoding="utf-8")
(OUT / "label.py").write_text(jl, encoding="utf-8")

g = meta["geometry"]
print("[생성] examples/cell")
print(f"  바디 {n_bodies}  ·  전열면적 {area * 1e6:.1f} mm2")
print(f"  도메인 x {g['Lx']:.0f} · y {g['Ly']:.2f} · z {g['Lz']:.3f} mm")
print(f"  입구면 {g['Ly'] * g['Lz']:.2f} mm2  (label 단계가 각도분리로 확보)")
