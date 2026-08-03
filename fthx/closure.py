"""
포러스 폐합 — j/f 상관식에서 Fluent 포러스 존 계수를 산출.

Fluent 포러스 존 (superficial velocity 기준):

    dp/L = (mu/alpha) * u_s + C2 * (rho/2) * u_s^2

공기측 전열은 `equilibrium` 모드에서 체적 열원으로 부과함:

    q''' = h * a_v * (T_solid - T_air)

⚠ 상관식은 임시임. 3-mode 규약상 최종적으로는 HX-Sim 을 호출해 받아와야 함:
    off-design    = 실험 j/f
    semi-empirical = 상관식 (여기 있는 것)
    on-design     = periodic cell CFD

여기 있는 것은 평판핀(plain) 근사이며, louver/wavy/slit 은 계수가 다름.
`fin_type` 별 분기는 HX-Sim 연동 시 그쪽 값으로 대체할 것.
"""
from __future__ import annotations

import math
from typing import Optional

from .params import FTHXParams


# ══════════════════════════════════════════════════════════════════
#  j / f 상관식 (임시 — HX-Sim 연동 전)
# ══════════════════════════════════════════════════════════════════
def jf_plain(Re_Dc: float, Fp_over_Dc: float) -> tuple[float, float]:
    """평판핀 근사. Re_Dc 300~5000 범위."""
    f = 0.508 * Re_Dc ** -0.521 * Fp_over_Dc ** -0.3
    j = 0.29 * Re_Dc ** -0.4
    return j, f


#: fin_type 별 보정 인자 (임시 — 실측/상관식으로 대체 필요)
FIN_FACTOR = {
    "plain":  (1.00, 1.00),
    "wavy":   (1.20, 1.45),
    "louver": (1.45, 1.90),
    "slit":   (1.35, 1.70),
}


def air_side(p: FTHXParams) -> dict:
    """공기측 포러스 계수 + 열전달계수."""
    d = p.derived()
    o = p.operating_derived()["air"]
    rho, mu = o["rho"], o["mu"]
    G, Re = o["G_max"], o["Re_Dc"]
    us = p.operating.air.V_face                      # superficial velocity
    W = d["depth_mm"] / 1000.0                       # 유동 방향 두께 [m]

    j0, f0 = jf_plain(Re, d["Fp_mm"] / d["D_c_mm"])
    kj, kf = FIN_FACTOR.get(p.fin.fin_type, (1.0, 1.0))
    j, f = j0 * kj, f0 * kf

    dp = f * d["A_o_over_A_c"] * G ** 2 / (2.0 * rho)   # 코어 전체 압력강하 [Pa]
    C2 = 2.0 * dp / (W * rho * us ** 2) if us > 0 else 0.0

    Pr = o["cp"] * mu / 0.0263                        # 공기 k ≈ 0.0263 W/mK
    h = j * G * o["cp"] / Pr ** (2.0 / 3.0)
    a_v = d["a_v_1perm"]

    return {"Re_Dc": Re, "j": j, "f": f, "fin_factor": [kj, kf],
            "dp_core_Pa": dp, "C2_1perm": C2,
            # 점성항은 난류 영역에서 관성항에 비해 작음. 0 으로 두면
            # 저유량에서 부정확해지므로 Darcy 항도 함께 산출
            "alpha_m2": (mu * us * W / dp) if dp > 0 else None,
            "h_W_m2K": h, "a_v_1perm": a_v, "hv_W_m3K": h * a_v,
            "porosity": d["porosity_gamma"],
            "correlation": f"plain x {p.fin.fin_type} factor (임시)",
            "note": "HX-Sim 연동 시 이 값을 그쪽 j/f 로 대체할 것",
            }


def fin_efficiency(p: FTHXParams, h: float) -> dict:
    """Schmidt 근사 핀효율. equilibrium 모드에서 h_eff = eta_o * h 로 씀."""
    d = p.derived()
    t, f = p.tube, p.fin
    r = d["D_c_mm"] / 2000.0                          # [m]
    # 등가 원형핀 반경 (사각 배열)
    XM = t.Pt / 2000.0
    XL = math.hypot(t.Pl, t.Pt / 2.0) / 2000.0 if t.layout == "staggered" \
        else t.Pl / 2000.0
    req = 1.27 * XM * math.sqrt(max(XL / XM - 0.3, 1e-6))
    phi = (req / r - 1.0) * (1.0 + 0.35 * math.log(max(req / r, 1.0001)))
    m = math.sqrt(2.0 * h / (f.k_fin * f.t_f / 1000.0))
    x = m * r * phi
    eta_f = math.tanh(x) / x if x > 1e-9 else 1.0
    A_fin_frac = d["A_o_fin_frac"]
    eta_o = 1.0 - A_fin_frac * (1.0 - eta_f)
    return {"r_m": r, "r_eq_m": req, "phi": phi, "m_1perm": m,
            "eta_fin": eta_f, "A_fin_frac": A_fin_frac, "eta_overall": eta_o,
            "h_eff_W_m2K": eta_o * h}


def ref_side(p: FTHXParams, n_circuit: int = 1) -> dict:
    """관내 냉매 — 단상. 물성과 Re 만 산출 (실형상 해상이므로 폐합 불필요)."""
    from . import distributor as DST
    fl = DST.Fluid(p.operating.ref.fluid, p.operating.ref.T_sat_in, 1.0)
    rho, mu = fl.props()
    m = p.operating.ref.m_total / max(1, n_circuit)
    D = p.tube.Di / 1000.0
    A = math.pi * D * D / 4.0
    v = m / (rho * A)
    return {"fluid": p.operating.ref.fluid, "rho": rho, "mu": mu,
            "m_per_circuit_kgs": m, "v_ms": v, "Re": rho * v * D / mu,
            "T_sat_C": p.operating.ref.T_sat_in}


def summary(p: FTHXParams, n_circuit: int = 1) -> dict:
    a = air_side(p)
    e = fin_efficiency(p, a["h_W_m2K"])
    r = ref_side(p, n_circuit)
    return {"air": a, "fin": e, "ref": r,
            "thermal_model": p.operating.thermal.model}
