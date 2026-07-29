#!/usr/bin/env python
"""CLI — 회로 패턴을 지정해 STEP + 메타 JSON 을 생성.

  python scripts/gen_case.py --pattern face_split -n 4
  python scripts/gen_case.py --pattern face_split -n 5 --plenum --m-total 0.03
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fthx import FTHXParams, circuits as CQC, distributor as DST, cad as CAD

ap = argparse.ArgumentParser()
ap.add_argument("--pattern", default="face_split", choices=list(CQC.GENERATORS))
ap.add_argument("-n", "--n-circuit", type=int, default=4)
ap.add_argument("--name", default=None)
ap.add_argument("--outdir", default="out")
ap.add_argument("--plenum", action="store_true", help="입구 플레넘·피더·porous jump 생성")
ap.add_argument("--fluid", default="R410A")
ap.add_argument("--T", type=float, default=7.0)
ap.add_argument("--quality", type=float, default=1.0)
ap.add_argument("--m-total", type=float, default=0.0, help="총 질량유량 [kg/s]")
a = ap.parse_args()

p = FTHXParams(name=a.name or f"fthx_{a.pattern}_{a.n_circuit}")
g = CQC.GENERATORS[a.pattern]
cs = g(p, a.n_circuit) if a.pattern in ("face_split", "interlaced") else g(p)

rep = CQC.build(p, cs)
print(f"[회로] {cs.pattern}  회로 {len(cs.circuits)}  벤드 {len(rep['bends'])}  "
      f"유로 평균 {rep['summary']['path_mean_mm']:.0f}mm  "
      f"편차 {rep['summary']['path_spread_pct']:.2f}%")
for w in rep["warnings"][:5]:
    print("  ⚠", w)
if rep["standoff"]["n_structural_crossing"]:
    print(f"  ✗ 구조적 교차 {rep['standoff']['n_structural_crossing']}건 — 회로 변경 필요")

pl = DST.PlenumSpec() if a.plenum else None
fl = DST.Fluid(a.fluid, a.T, a.quality) if (a.plenum and a.m_total > 0) else None
meta = CAD.export(p, outdir=a.outdir, cs=cs, plenum=pl, fluid=fl, m_total=a.m_total)

d = (meta.get("plenum") or {}).get("distribution")
if d:
    print(f"[분배] 편차 {d['before']['maldist_pct']:.2f}% → {d['after']['maldist_pct']:.4f}%")
    for r in d["jump_sizing"]["rows"]:
        print(f"   {r['id']}  C2 = {r['C2_1perm']:8.1f} 1/m")
print("[출력]", meta["_files"]["step"], "|", meta["_files"]["json"])
