"""메시 사이징 — 형상 파라미터에서 셀 크기를 유도.

범용 CFD 자동화가 깨지는 지점이 케이스마다 사람이 사이징을 손으로 맞추는
것인데, 핀-튜브 열교환기는 위상이 고정이라 **식으로 쓸 수 있음**.
정수 몇 개만 정하면 어떤 파라미터 조합에도 크기가 자동으로 나옴.
"""
from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from .params import FTHXParams


class MeshSpec(BaseModel):
    N_gap: int = Field(10, ge=2, description="관 사이 최소 간격(Pt-Do) 분할 수")
    N_wall: int = Field(1, ge=1,
        description="관벽 두께 방향 층수. conformal 메시에서 관 표면은 코어·냉매와 "
                    "공유되므로 이 값으로 '표면' 크기를 정하면 이웃까지 조밀해짐. "
                    "두께 방향은 thin-volume 으로 따로 확보할 것")
    N_d: int = Field(12, ge=4, description="관 내경 분할 수")
    N_arc: int = Field(24, ge=8, description="벤드 반원 분할 수")
    growth: float = Field(1.2, gt=1, description="성장률")
    cells_per_gap: int = Field(1, ge=1,
        description="Fluent Proximity 의 '틈새당 셀 수'. 기본 3 이면 관벽을 "
                    "틈새로 보고 t/3 까지 자동 세분화해 이웃 존까지 폭증함")


def sizing(p: FTHXParams, ms: Optional[MeshSpec] = None) -> dict:
    """바디 클래스별 셀 크기 [mm]와 워크플로우에 넣을 min/max."""
    ms = ms or MeshSpec()
    t = p.tube
    t_wall = (t.Do - t.Di) / 2.0
    h_air = (t.Pt - t.Do) / ms.N_gap
    h_wall = t_wall / ms.N_wall
    h_ref = t.Di / ms.N_d
    R_min = t.Pt / 2.0
    h_bend = min(h_ref, math.pi * R_min / ms.N_arc)
    # 표면 크기는 '면방향' 요구만 반영함. 관벽 두께는 표면 크기로 풀지 않음
    # (관 표면은 코어·냉매와 공유되므로 얇게 잡으면 이웃까지 같이 조밀해짐)
    per_body = {
        "fluid_air_up/down": h_air * 2.0,      # 연장부는 굵게
        "fluid_air_core_*": h_air,
        "solid_tube_*": h_ref,                 # 이웃과 공유 → 관내와 같은 크기
        "fluid_ref_*": h_ref,
        "*_bend_*": h_bend,
    }
    h_min = min(per_body.values())
    h_max = max(per_body.values())

    # Fluent 의 Min size 는 하한선이지 목표가 아님. 곡률·근접 조건이 요구할 때만
    # 그 크기로 내려감. 관벽처럼 얇지만 곡률이 완만한 바디는 자동으로 안 잡히므로
    # Local Sizing 을 직접 걸어야 함. (2025R1 실측: 관벽 0.65mm 에 셀 1겹만 들어감)
    local = [
        {"name": "tube-inner", "scope": "fluid_ref_*", "type": "face-and-body",
         "size_mm": round(h_ref, 3), "why": "관내 유동"},
    ]
    if p.domain.include_bends:
        local.append({"name": "bend", "scope": "*_bend_*", "type": "face-and-body",
                      "size_mm": round(h_bend, 3), "why": "비정형 벤드 곡률"})

    # ── 관벽 처리 전략 ────────────────────────────────────────
    # 고전도 박벽은 두께 방향 온도구배가 없음:  Bi = h·t/k
    # 구리 0.65mm, h~350 W/m²K → Bi ~ 6e-4.  3겹으로 나눌 이유가 없음.
    h_rep = 350.0                                    # 대표 열전달계수 [W/m²K]
    Bi = h_rep * (t_wall / 1000.0) / t.k_tube
    wall = {
        "t_wall_mm": t_wall,
        "Biot": Bi,
        "isothermal_through_thickness": Bi < 0.01,
        "strategy": ("thin_volume" if Bi < 0.01 else "resolved"),
        "layers": ms.N_wall,
        "note": (f"Bi={Bi:.1e} (<0.01) → 두께 방향 등온. 표면을 조밀하게 만들 "
                 f"필요가 없음. Fluent 의 Thin Volume Mesh 로 두께 방향 "
                 f"{ms.N_wall}층만 넣으면 됨. 표면 크기로 두께를 풀려 하면 "
                 f"관 표면이 코어·냉매와 공유되므로 이웃 존까지 폭증함 "
                 f"(2025R1 실측: 69k → 1.31M 셀).")
                if Bi < 0.01 else
                f"Bi={Bi:.1e} — 두께 방향 구배 무시 못 함. 실해상 필요.",
        "alternative": "shell conduction (관벽 바디를 아예 빼고 벽면 두께로 처리)",
    }

    # ── 표면 메시 작업에 반드시 지정할 값 ─────────────────────
    # Fluent 의 Proximity 는 기본이 '틈새당 셀 3개'. 관벽(0.65mm)을 틈새로
    # 인식해 자동으로 t/3 까지 세분화함. 2025R1 실측: Local Sizing 을 지워도
    # 셀이 1.31M 로 그대로였던 원인이 이것이었음.
    # Min Size 가 하한선이므로 이것을 올려두면 Proximity 요구도 막힘.
    surface = {
        "min_mm": round(h_min, 3),
        "max_mm": round(h_max, 3),
        "growth": ms.growth,
        "cells_per_gap": ms.cells_per_gap,
        "why_min": (f"관벽 {t_wall:.2f}mm 가 '틈새'로 인식돼 자동 세분화되는 것을 "
                    f"막는 하한선. 이 값을 {round(h_min,3)} 미만으로 두면 "
                    f"Proximity 가 t/cells_per_gap 까지 내려감"),
    }

    return {
        "surface": surface,
        "wall": wall,
        "local_sizing": local,
        "spec": ms.model_dump(),
        "h_air_mm": h_air, "h_wall_mm": h_wall,
        "h_ref_mm": h_ref, "h_bend_mm": h_bend,
        "per_body_mm": per_body,
        "workflow_min_mm": round(h_min, 3),
        "workflow_max_mm": round(h_max, 3),
        "growth": ms.growth,
        "note": (f"관벽 두께 {(t.Do-t.Di)/2:.2f}mm 를 {ms.N_wall}분할 하려면 "
                 f"최소 크기가 {h_wall:.3f}mm 여야 함. 이보다 굵게 잡으면 "
                 f"관벽에 셀이 안 들어가 conjugate 열전달이 성립하지 않음."),
    }


# ══════════════════════════════════════════════════════════════════
#  셀 수 추정 — Fluent 실측 보정
# ══════════════════════════════════════════════════════════════════
# tutorial(관1개, 68,641셀) 과 probe(관3개+벤드2, 164,461셀) 를 Fluent 2025R1
# 로 실제 메싱해 얻은 패킹계수.  cells = K · V / h³
# 등방 h³ 나눗셈만으로는 성장·근접 세분화를 못 담기 때문에 필요함.
CALIB = {
    "source": "Fluent 2025R1 Watertight · tutorial + probe 실측",
    "K": {"core": 1.902, "ref": 0.715, "wall": 0.845,
          "bend_f": 0.922, "bend_s": 0.975, "up": 2.901, "down": 2.296},
    # 두 케이스 간 편차 — 추정 불확실도
    # 두 케이스 간 편차 — 추정 불확실도
    "spread_pct": {"core": 17, "ref": 1, "wall": 1,
                   "bend_f": 3, "bend_s": 3, "up": 40, "down": 40},
    "caveat": ("상·하류 연장의 K 는 보정 케이스(연장 80mm)에서 뽑았음. "
               "실제로는 코어 계면에서 자라는 구간이 8~10mm 남짓이라, "
               "연장이 길수록 과대추정될 가능성이 큼. 편차를 ±40% 로 둠."),
}


def zone_volumes(p: FTHXParams, cs=None) -> dict:
    """존 클래스별 체적 [mm³]."""
    t, b = p.tube, p.fin_pack
    W, H, Lf = b["x1"] - b["x0"], b["y1"] - b["y0"], b["L_fin"]
    n = t.Nr * t.Nt
    A_in = math.pi / 4 * t.Di ** 2
    A_wall = math.pi / 4 * (t.Do ** 2 - t.Di ** 2)
    dk = p.duct_box
    Hd, Ld = dk["y1"] - dk["y0"], dk["z1"] - dk["z0"]

    V = {"core": W * H * Lf - n * math.pi / 4 * t.Do ** 2 * Lf,
         "ref": n * A_in * t.L,
         "wall": n * A_wall * t.L,
         "up": p.domain.L_up * Hd * Ld,
         "down": p.domain.L_down * Hd * Ld}
    if not dk["sealed"]:
        V["core"] += 0.0            # 바이패스는 core 크기로 처리
        V["bypass"] = (Hd * Ld - H * Lf) * W
    if cs is not None:
        from . import circuits as CQC
        bends = CQC.derive_bends(p, cs)
        CQC.resolve_standoff(p, bends)
        Lb = sum(b_.path_len for b_ in bends)
        V["bend_f"] = Lb * A_in
        V["bend_s"] = Lb * A_wall
    return V


def estimate(p: FTHXParams, cs=None, ms: Optional[MeshSpec] = None) -> dict:
    """실측 보정된 셀 수 추정. 등방 h³ 만 쓰던 기존 추정과 달리
       성장·근접 세분화를 패킹계수로 반영함."""
    s = sizing(p, ms)
    V = zone_volumes(p, cs)
    h = {"core": s["h_air_mm"], "bypass": s["h_air_mm"],
         "ref": s["h_ref_mm"], "wall": s["h_ref_mm"],
         "bend_f": s["h_bend_mm"], "bend_s": s["h_bend_mm"],
         "up": s["workflow_max_mm"], "down": s["workflow_max_mm"]}
    K, SP = CALIB["K"], CALIB["spread_pct"]
    rows, total, lo, hi = [], 0.0, 0.0, 0.0
    for k, vol in V.items():
        kk = K.get(k, K["core"])
        sp = SP.get(k, 20) / 100.0
        c = kk * vol / h[k] ** 3
        rows.append({"zone": k, "V_mm3": vol, "h_mm": h[k],
                     "K": kk, "cells": c, "spread_pct": SP.get(k, 20)})
        total += c
        lo += c * (1 - sp)
        hi += c * (1 + sp)
    rows.sort(key=lambda r: -r["cells"])
    for r in rows:
        r["frac"] = r["cells"] / total if total else 0.0
    return {"calibration": CALIB["source"], "sizing": s,
            "zones": rows, "total": total, "low": lo, "high": hi,
            "note": "K·V/h³ (Fluent 실측 보정). 관 관련 존은 ±1%, "
                    "상·하류 연장은 ±30% 편차"}


def wall_treatment(p: FTHXParams, n_circuit: int = 4,
                   fluid=None, m_total: Optional[float] = None) -> dict:
    """관내 y+ 판정. 프리즘이 필요한지 여기서 결정됨."""
    from . import distributor as DST
    fl = fluid or DST.Fluid(p.operating.ref.fluid, p.operating.ref.T_sat_in, 1.0)
    rho, mu = fl.props()
    m = (m_total or p.operating.ref.m_total) / max(1, n_circuit)
    D = p.tube.Di / 1000.0
    A = math.pi * D * D / 4.0
    v = m / (rho * A)
    Re = rho * v * D / mu
    f = DST.churchill_f(Re, 1.5e-6 / D)
    u_tau = math.sqrt(f / 8.0 * v * v)
    h1 = sizing(p)["h_ref_mm"]                    # 프리즘 없을 때 첫 셀
    y_plus = (h1 / 2 / 1000.0) * u_tau / (mu / rho)
    if y_plus > 300:
        verdict, need = "벽함수 상한 초과", "셀을 더 촘촘히"
    elif y_plus >= 30:
        verdict, need = "벽함수 적용 가능", "프리즘 불필요"
    elif y_plus > 5:
        verdict, need = "완충층 — 피해야 함", "프리즘으로 y+<5 또는 >30 으로"
    else:
        verdict, need = "저Re 해상", "Enhanced Wall Treatment"
    return {"n_circuit": n_circuit, "m_per_circuit_kgs": m, "v_ms": v, "Re": Re,
            "u_tau_ms": u_tau, "first_cell_mm": h1, "y_plus": y_plus,
            "verdict": verdict, "action": need,
            "prism_needed": not (30 <= y_plus <= 300)}


def feasibility(p: FTHXParams, cs=None, budget: float = 20e6,
                ms: Optional[MeshSpec] = None) -> dict:
    """실현가능성 게이트."""
    e = estimate(p, cs, ms)
    s = e["sizing"]
    issues = []
    if e["high"] > budget:
        issues.append(f"셀 예산 초과 가능: 최대 추정 {e['high']/1e6:.1f}M > "
                      f"{budget/1e6:.0f}M")
    if s["wall"]["strategy"] == "resolved":
        issues.append("관벽 Bi>0.01 — 두께 방향 실해상 필요, 셀 급증 예상")
    ext = sum(r["cells"] for r in e["zones"] if r["zone"] in ("up", "down"))
    if ext / e["total"] > 0.25:
        issues.append(f"상·하류 연장이 전체의 {ext/e['total']*100:.0f}% — "
                      "L_down 축소나 Max size 증가 검토")
    if e["total"] > 0:
        ext_cells = sum(r["cells"] for r in e["zones"] if r["zone"] in ("up", "down"))
        per_mm = ext_cells / max(1e-9, p.domain.L_up + p.domain.L_down)
        issues_hint = {"ext_cells_per_mm": per_mm,
                       "L_down_mm": p.domain.L_down,
                       "save_by_halving_L_down": per_mm * p.domain.L_down / 2}
    else:
        issues_hint = {}
    return {"ok": not issues, "issues": issues, "hint": issues_hint,
            "total_M": e["total"] / 1e6, "range_M": [e["low"] / 1e6, e["high"] / 1e6],
            "budget_M": budget / 1e6, "estimate": e}
