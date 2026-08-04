#!/usr/bin/env python
"""results.csv -> 성능 지표. **표준 라이브러리만 사용** (pydantic 불필요).

Fluent 서버에는 pip 이 없어 fthx 패키지를 못 쓰는 경우가 있음.
저널이 함께 내보낸 closure.json / case.json 에 필요한 값이 다 들어 있으므로
그것만 읽어 계산함.

  python scripts/post_standalone.py examples/probe
  python scripts/post_standalone.py examples/probe --dp 4.1519 --dpo -0.0032 --tout 297.53
"""
import argparse
import csv
import json
import math
import os
import sys


def load(d, name):
    p = os.path.join(d, name)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def read_results(d):
    p = os.path.join(d, "results.csv")
    if not os.path.exists(p):
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}
    out = {}
    for k, v in rows[-1].items():
        if k == "case" or v in ("", None):
            continue
        try:
            out[k] = float(v)
        except ValueError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="케이스 폴더 (results.csv / case.json / closure.json)")
    ap.add_argument("--dp", type=float, help="p_air_in [Pa] (results.csv 없을 때)")
    ap.add_argument("--dpo", type=float, default=0.0, help="p_air_out [Pa]")
    ap.add_argument("--tout", type=float, help="t_air_out [K]")
    ap.add_argument("-o", "--out", help="지표를 CSV 로 추가 저장")
    a = ap.parse_args()

    d = a.dir
    case = load(d, "case.json")
    clos = load(d, "closure.json")
    res = read_results(d)

    if a.dp is not None:
        res["p_air_in"] = a.dp
        res["p_air_out"] = a.dpo
    if a.tout is not None:
        res["t_air_out"] = a.tout
    if not res:
        print("results.csv 도 없고 --dp/--tout 도 없음")
        return 1

    op = case.get("operating", {})
    air_op = op.get("air", {})
    ref_op = op.get("ref", {})
    der = case.get("derived", {})
    od = case.get("operating_derived", {}).get("air", {})

    rho = od.get("rho", 1.1686)
    cp = od.get("cp", 1006.0)
    V = air_op.get("V_face", 2.0)
    T_in = air_op.get("T_in", 27.0) + 273.15
    T_ref = ref_op.get("T_sat_in", 7.0) + 273.15
    A_front = der.get("A_front_mm2", 0.0) / 1e6

    m_air = abs(res.get("m_air_in") or 0.0) or rho * V * A_front
    p_in = res.get("p_air_in")
    p_out = res.get("p_air_out", 0.0)
    t_out = res.get("t_air_out")

    print("=" * 58)
    print("케이스: %s" % case.get("name", os.path.basename(d.rstrip("/"))))
    print("공기 %.2f m/s · %.2f K → 냉매 %.2f K · 유량 %.4f kg/s"
          % (V, T_in, T_ref, m_air))
    print("=" * 58)

    rows = []
    if p_in is not None:
        dp = p_in - p_out
        rows.append(("dP_air_Pa", dp))
        pred = (clos.get("air") or {}).get("dp_core_Pa")
        if pred:
            rows.append(("  예측(closure)", pred))
            rows.append(("  오차 %", (dp / pred - 1) * 100))

    if t_out is not None:
        Q = m_air * cp * (T_in - t_out)
        rows += [("T_air_out_K", t_out), ("Q_W", Q)]
        dT1, dT2 = T_in - T_ref, t_out - T_ref
        if dT1 > 0 and dT2 > 0 and abs(dT1 - dT2) > 1e-9:
            lmtd = (dT1 - dT2) / math.log(dT1 / dT2)
            rows += [("LMTD_K", lmtd), ("UA_W_K", Q / lmtd)]
        if abs(T_in - T_ref) > 1e-9:
            eps = (T_in - t_out) / (T_in - T_ref)
            rows.append(("effectiveness", eps))
            if 0 < eps < 1:
                ntu = -math.log(1 - eps)
                rows += [("NTU", ntu), ("UA_from_NTU_W_K", ntu * m_air * cp)]
        fin = clos.get("fin") or {}
        if fin.get("h_eff_W_m2K") and der.get("A_o_mm2"):
            ua_pred = fin["h_eff_W_m2K"] * der["A_o_mm2"] / 1e6
            rows.append(("  UA 예측(공기측만)", ua_pred))
            rows.append(("  → CFD 가 더 작아야 정상", 0.0))

    for k, v in rows:
        print("  %-26s %14.4f" % (k, v))

    if a.out:
        flat = {k.strip(): v for k, v in rows if not k.startswith("  ")}
        flat["case"] = case.get("name", "")
        new = not os.path.exists(a.out)
        with open(a.out, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(flat))
            if new:
                w.writeheader()
            w.writerow(flat)
        print("\n[저장] %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
