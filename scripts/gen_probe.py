#!/usr/bin/env python
"""메싱 시험용 최소 케이스 — 1열 × 3단, 짧은 관.

전체 케이스(190 바디)로 첫 메시를 돌리면 오래 걸리고 실패 시 원인 분리가
어려움. 구조적으로 확인해야 할 것(포러스↔관벽 conformal, 벤드 메싱,
존 이름 승계)은 전부 들어 있으면서 1~2분에 끝나는 크기임.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fthx import FTHXParams, TubeSpec, FinSpec, DomainSpec, circuits as CQC, cad as CAD

p = FTHXParams(
    name="probe_small",
    tube=TubeSpec(Do=9.52, Di=8.22, L=100, Nr=1, Nt=3, Pt=25.4, Pl=22.0,
                  layout="inline"),
    fin=FinSpec(FPI=14, t_f=0.115, L_fin=80),
    domain=DomainSpec(L_up=40, L_down=80, include_bends=True,
                      include_tube_fluid=True, split_core_by_row=True),
    export={"write_pcurves": False},          # 임포트 빠르게
)
cs = CQC.gen_single(p)                        # 관 3개를 하나로 잇는 단일 회로
rep = CQC.build(p, cs)
print(f"[회로] 단일, 관 {len(cs.circuits[0].tubes)}개, 벤드 {len(rep['bends'])}개, "
      f"검증 ok={rep['ok']}")

meta = CAD.export(p, outdir="out", cs=cs)
d = p.derived()
print(f"[형상] 코어 {d['depth_mm']:.0f} x {d['height_mm']:.0f} x {d['L_fin_mm']:.0f} mm, "
      f"핀 {d['N_fin']}장, γ={d['porosity_gamma']:.4f}")
print(f"[STEP] {meta['_files']['step']}")

import re
names = re.findall(r"PRODUCT\('([^']+)'", Path(meta['_files']['step']).read_text(errors='ignore'))
bodies = [n for n in names[1:]]
print(f"[바디] {len(bodies)}개")
for n in bodies:
    print(f"    {n}")
