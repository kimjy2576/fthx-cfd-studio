#!/usr/bin/env python
"""results.csv → 성능 지표 (dP, Q, LMTD, UA, eps/NTU) + 예측 대조.

  python scripts/post.py examples/probe/results.csv --preset probe
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fthx import FTHXParams, presets, post

ap = argparse.ArgumentParser()
ap.add_argument("csv", type=Path)
ap.add_argument("--preset", choices=list(presets.PRESETS))
ap.add_argument("--case", type=Path, help="case.json 에서 파라미터")
ap.add_argument("-n", "--n-circuit", type=int, default=1)
ap.add_argument("-o", "--out", type=Path, help="지표를 CSV 로 추가 저장")
a = ap.parse_args()

if a.case:
    doc = json.loads(a.case.read_text(encoding="utf-8"))
    p = FTHXParams(**{k: v for k, v in doc.items() if k in FTHXParams.model_fields})
elif a.preset:
    p = presets.PRESETS[a.preset]()
else:
    p = FTHXParams()

raw = post.read_csv(str(a.csv))
print(f"[원시] {raw}")
m = post.metrics(p, raw, a.n_circuit)
print("\n[성능]")
for k, v in m.items():
    print(f"  {k:<22}{v:>14.4f}" if isinstance(v, float) else f"  {k:<22}{v}")

c = post.compare_prediction(p, m, a.n_circuit)
if c["rows"]:
    print("\n[예측 대조]")
    for r in c["rows"]:
        e = f"{r['error_pct']:+7.2f}%" if r.get("error_pct") is not None else "  -  "
        print(f"  {r['quantity']:<12} 예측 {r['predicted']:9.3f}  "
              f"CFD {r['cfd']:9.3f}  {e}   {r.get('note','')}")

if a.out:
    import csv
    row = post.to_row(p, m)
    new = not a.out.exists()
    with open(a.out, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"\n[저장] {a.out} ({len(row)}열)")
