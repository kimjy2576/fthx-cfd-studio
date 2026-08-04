"""
후처리 — CFD 결과에서 성능 지표를 산출.

Fluent 저널이 `results.csv` 를 직접 쓰고, 이 모듈이 그것을 읽어 지표를 계산함.
로그 파싱은 하지 않음 — 로그 형식은 버전마다 바뀌지만 CSV 는 안정적임.

지표
----
    dP_air      코어 압력강하 [Pa]      = P_in - P_out
    Q           전열량 [W]              = m_air * cp * (T_in - T_out)
    LMTD        대수평균온도차 [K]
    UA          총괄전열계수 x 면적 [W/K] = Q / LMTD
    eps, NTU    유효도-NTU (교차검증용)
"""
from __future__ import annotations

import math
from typing import Optional

from .params import FTHXParams


#: 저널이 쓰는 CSV 의 열 이름 (저널과 이 모듈이 공유하는 계약)
FIELDS = ["p_air_in", "p_air_out", "t_air_out", "m_air_in",
          "t_ref_out", "m_ref_in"]


def metrics(p: FTHXParams, raw: dict, n_circuit: int = 1) -> dict:
    """CFD 원시값 → 성능 지표.

    raw 는 저널이 쓴 results.csv 의 한 행 (단위: Pa, K, kg/s).
    누락된 항목은 형상·운전 조건에서 보완함.
    """
    o = p.operating
    air = p.operating_derived()["air"]
    d = p.derived()

    T_in = o.air.T_in + 273.15
    T_ref = o.ref.T_sat_in + 273.15

    p_in = raw.get("p_air_in")
    p_out = raw.get("p_air_out", 0.0)
    t_out = raw.get("t_air_out")
    m_air = abs(raw.get("m_air_in") or 0.0) or \
        air["rho"] * o.air.V_face * d["A_front_mm2"] / 1e6

    out: dict = {"m_air_kgs": m_air, "T_air_in_K": T_in, "T_ref_K": T_ref}

    if p_in is not None:
        out["dP_air_Pa"] = p_in - p_out

    if t_out is None:
        return out

    cp = air["cp"]
    Q = m_air * cp * (T_in - t_out)
    out.update({"T_air_out_K": t_out, "Q_W": Q, "cp": cp})

    dT1, dT2 = T_in - T_ref, t_out - T_ref
    if dT1 > 0 and dT2 > 0 and abs(dT1 - dT2) > 1e-9:
        lmtd = (dT1 - dT2) / math.log(dT1 / dT2)
        out["LMTD_K"] = lmtd
        out["UA_W_K"] = Q / lmtd

    # 유효도-NTU 로 교차검증 (냉매 등온 가정)
    C = m_air * cp
    if abs(T_in - T_ref) > 1e-9:
        eps = (T_in - t_out) / (T_in - T_ref)
        out["effectiveness"] = eps
        if 0 < eps < 1:
            ntu = -math.log(1.0 - eps)
            out["NTU"] = ntu
            out["UA_from_NTU_W_K"] = ntu * C
    return out


def compare_prediction(p: FTHXParams, m: dict, n_circuit: int = 1) -> dict:
    """closure 예측과 CFD 실측 대조. 어긋나면 설정을 의심할 근거가 됨."""
    from . import closure
    c = closure.summary(p, n_circuit)
    a, e = c["air"], c["fin"]
    d = p.derived()

    rows = []
    if "dP_air_Pa" in m:
        rows.append({"quantity": "dP_air_Pa", "predicted": a["dp_core_Pa"],
                     "cfd": m["dP_air_Pa"]})
    if "UA_W_K" in m:
        # 공기측 저항만 고려한 상한. 관벽·냉매측을 더하면 이보다 작아야 함
        ua_air = e["h_eff_W_m2K"] * d["A_o_mm2"] / 1e6
        rows.append({"quantity": "UA_W_K", "predicted": ua_air,
                     "cfd": m["UA_W_K"],
                     "note": "예측은 공기측만 — CFD 가 더 작은 것이 정상"})
    for r in rows:
        pr, cf = r["predicted"], r["cfd"]
        r["error_pct"] = (cf / pr - 1.0) * 100.0 if pr else None
    return {"rows": rows}


def read_csv(path: str) -> dict:
    """저널이 쓴 results.csv 를 읽어 dict 로."""
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}
    r = rows[-1]
    return {k: (float(v) if v not in ("", None) else None)
            for k, v in r.items() if k != "case"}


def to_row(p: FTHXParams, m: dict, extra: Optional[dict] = None) -> dict:
    """HPWD-DataManager 스키마에 맞춘 한 행."""
    d = p.derived()
    o = p.operating
    row = {
        "case": p.name,
        "Nr": p.tube.Nr, "Nt": p.tube.Nt, "FPI": p.fin.FPI,
        "fin_type": p.fin.fin_type, "layout": p.tube.layout,
        "Do_mm": p.tube.Do, "Di_mm": p.tube.Di,
        "Pt_mm": p.tube.Pt, "Pl_mm": p.tube.Pl,
        "L_fin_mm": d["L_fin_mm"], "A_o_m2": d["A_o_mm2"] / 1e6,
        "sigma": d["sigma"], "porosity": d["porosity_gamma"],
        "V_face_ms": o.air.V_face, "T_air_in_C": o.air.T_in,
        "RH_in_pct": o.air.RH_in,
        "refrigerant": o.ref.fluid, "T_sat_C": o.ref.T_sat_in,
        "m_ref_kgs": o.ref.m_total, "thermal_model": o.thermal.model,
    }
    for k in ("dP_air_Pa", "Q_W", "UA_W_K", "LMTD_K", "effectiveness", "NTU",
              "T_air_out_K", "m_air_kgs"):
        if k in m:
            row[k] = m[k]
    if extra:
        row.update(extra)
    return row
