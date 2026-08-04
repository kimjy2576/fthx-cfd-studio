#!/usr/bin/env python
"""cell_results.csv → j, f  (표준 라이브러리만).

  python scripts/cell_jf.py examples/cell
"""
import argparse, csv, json, math, os, sys

ap = argparse.ArgumentParser()
ap.add_argument("dir")
ap.add_argument("--q", type=float, help="벽면 총 열유속 [W] (없으면 엔탈피로)")
a = ap.parse_args()

def load(n):
    p = os.path.join(a.dir, n)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}

case = load("case.json")
csvp = os.path.join(a.dir, "cell_results.csv")
if not os.path.exists(csvp):
    print("cell_results.csv 없음 — 해석을 먼저 돌릴 것"); sys.exit(1)
r = list(csv.DictReader(open(csvp, encoding="utf-8")))[-1]
g = lambda k: float(r[k]) if r.get(k) not in ("", None) else None

p_in, p_out, t_out = g("p_in"), g("p_out"), g("t_out")
A, u_max, T_in, T_w = g("area_m2"), g("u_max"), g("T_in"), g("T_wall")
od = (case.get("operating_derived") or {}).get("air", {})
der = case.get("derived", {})
rho = od.get("rho", 1.1686); cp = od.get("cp", 1016.1); mu = od.get("mu", 1.84e-5)
G = od.get("G_max", rho * u_max)

print("=" * 56)
print("주기 단위셀 → j / f")
print("=" * 56)
dp = p_in - p_out
print(f"  dP           {dp:12.4f} Pa")
print(f"  T_out        {t_out:12.4f} K   (입구 {T_in}, 벽 {T_w})")

AoAc = der.get("A_o_over_A_c")
if AoAc:
    f = dp * 2 * rho / (G ** 2 * AoAc)
    print(f"  f            {f:12.5f}   (A_o/A_c = {AoAc:.2f})")

dT1, dT2 = T_in - T_w, t_out - T_w
if dT1 > 0 and dT2 > 0:
    lmtd = (dT1 - dT2) / math.log(dT1 / dT2)
    # 셀을 지나는 공기 질량유량: G x 최소유동면적. 여기서는 엔탈피로 역산
    q = a.q
    if q is None and od.get("A_front_m2"):
        pass
    print(f"  LMTD         {lmtd:12.4f} K")
    if q:
        h = q / (A * lmtd)
        Pr = cp * mu / 0.0263
        j = h / (G * cp) * Pr ** (2 / 3)
        print(f"  Q            {q:12.4f} W")
        print(f"  h            {h:12.4f} W/m2K")
        print(f"  j            {j:12.5f}   (Pr {Pr:.3f})")
    else:
        print("  → h·j 는 --q 로 벽면 열유속을 주거나 로그의 Net 값을 쓸 것")
