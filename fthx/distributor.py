"""
다중 입출구 처리 — 병렬 회로 유량 분배 예측 · porous jump 계수 산정

배경
----
회로가 C개면 냉매 입구도 C개가 됨. 회로별로 mass-flow-inlet 을 따로 주면
'분배를 알고 싶은데 분배를 입력해야 하는' 모순이 생김.
→ 입구 플레넘 하나로 묶고 총유량만 경계조건으로 주면, 분배는 회로별
   유로 저항 차이로 자연히 풀림.  단상 전제.

이 모듈이 하는 일
----------------
1) 회로별 유로 저항으로 병렬 분배를 직접 푼다 (CFD 돌리기 전에 편차를 본다)
2) 균등 분배를 만들려면 회로마다 얼마의 추가 저항이 필요한지 → Fluent
   porous jump 의 C2 (관성 저항 계수) 로 환산한다

⚠ 단상 한정. 2상에서는 분배가 압력강하가 아니라 입구 quality 와 관성 분리에
   지배되므로 이 모델이 성립하지 않음.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from scipy.optimize import brentq

from .params import FTHXParams
from . import circuits as CQC

try:
    import CoolProp.CoolProp as CP
    HAS_CP = True
except Exception:                                    # pragma: no cover
    HAS_CP = False


# ══════════════════════════════════════════════════════════════════
#  물성
# ══════════════════════════════════════════════════════════════════
@dataclass
class Fluid:
    name: str = "R410A"
    T_C: float = 7.0
    quality: float = 1.0          # 1=포화증기, 0=포화액 (단상 근사용)
    rho: Optional[float] = None   # kg/m3  (직접 주면 CoolProp 무시)
    mu: Optional[float] = None    # Pa·s

    def props(self) -> tuple[float, float]:
        if self.rho is not None and self.mu is not None:
            return self.rho, self.mu
        if not HAS_CP:
            raise RuntimeError("CoolProp 없음 — rho, mu 를 직접 지정할 것")
        T = self.T_C + 273.15
        return (CP.PropsSI("D", "T", T, "Q", self.quality, self.name),
                CP.PropsSI("V", "T", T, "Q", self.quality, self.name))


@dataclass
class PlenumSpec:
    """입구 분배기 / 출구 헤더 + 피더 튜브"""
    D_plenum: float = 16.0        # mm, 플레넘 내경
    offset: float = 45.0          # mm, 코어 끝면에서 플레넘 축까지
    x_off: float = -35.0          # mm, 코어 앞면(x0) 기준 플레넘 축의 x 위치
    D_feed: float = 4.0           # mm, 피더 내경 (모세관 상당)
    split_frac: float = 0.5       # 피더를 둘로 쪼개는 위치 (porous jump 면)
    jump_thick: float = 1.0       # mm, porous jump 매질 두께
    auto_offset: bool = False     # 벤드와 안 겹치도록 offset 자동 확대
    # ── 입구 발달 스터브 (플레넘 축 방향 연장관) ──────────────
    stub_len: float = 0.0         # mm, 0 이면 스터브 없음(기존 동작)
    D_stub: Optional[float] = None  # mm, None → 플레넘 내경과 동일(단차 없음)
    stub_auto: bool = False       # 발달 길이만큼 자동 확보
    stub_criterion: Literal["full", "practical"] = "practical"

    def stub_dia(self) -> float:
        return self.D_stub if self.D_stub is not None else self.D_plenum


# ══════════════════════════════════════════════════════════════════
#  마찰
# ══════════════════════════════════════════════════════════════════
def churchill_f(Re: float, rr: float = 0.0) -> float:
    """Churchill(1977) — 층류·천이·난류 전 영역 연속. Darcy f."""
    Re = max(Re, 1e-3)
    A = (2.457 * math.log(1.0 / ((7.0 / Re) ** 0.9 + 0.27 * rr))) ** 16
    B = (37530.0 / Re) ** 16
    return 8.0 * ((8.0 / Re) ** 12 + 1.0 / (A + B) ** 1.5) ** (1.0 / 12.0)


# ══════════════════════════════════════════════════════════════════
#  회로 저항
# ══════════════════════════════════════════════════════════════════
@dataclass
class Leg:
    """병렬 가지 하나 = 피더 + 회로 유로"""
    cid: str
    L_path: float        # mm, 관+벤드 유로길이
    n_bend: int
    L_feed: float        # mm, 피더 길이
    jump_C2: float = 0.0 # 1/m, porous jump 관성계수 (0 = 없음)


def leg_dp(leg: Leg, m: float, p: FTHXParams, pl: PlenumSpec,
           rho: float, mu: float, K_bend: float = 0.7,
           roughness: float = 1.5e-6) -> float:
    """가지 압력강하 [Pa].  유로 길이에 벤드 호길이가 이미 포함돼 있으므로
       K_bend 는 곡률에 의한 '추가' 손실만 담당함."""
    out = 0.0
    for D_mm, L_mm, nb in ((pl.D_feed, leg.L_feed, 0),
                           (p.tube.Di, leg.L_path, leg.n_bend)):
        if L_mm <= 0:
            continue
        D = D_mm / 1000.0
        A = math.pi * D * D / 4.0
        v = m / (rho * A)
        Re = rho * v * D / mu
        f = churchill_f(Re, roughness / D)
        out += (f * (L_mm / 1000.0) / D + nb * K_bend) * 0.5 * rho * v * v
    if leg.jump_C2 > 0:                       # porous jump (관성항)
        D = pl.D_feed / 1000.0
        v = m / (rho * math.pi * D * D / 4.0)
        out += leg.jump_C2 * 0.5 * rho * v * v * (pl.jump_thick / 1000.0)
    return out


def _m_from_dp(leg, dp, *a, **kw) -> float:
    """단조 증가하는 dp(m) 을 역으로 풀어 m 을 구함"""
    if dp <= 0:
        return 0.0
    hi = 1e-4
    while leg_dp(leg, hi, *a, **kw) < dp and hi < 10.0:
        hi *= 2.0
    return brentq(lambda m: leg_dp(leg, m, *a, **kw) - dp, 0.0, hi, xtol=1e-12)


def solve_split(legs: List[Leg], m_total: float, p: FTHXParams, pl: PlenumSpec,
                fl: Fluid, K_bend: float = 0.7) -> dict:
    """병렬 가지가 같은 ΔP 를 갖도록 유량 분배를 품"""
    rho, mu = fl.props()
    args = (p, pl, rho, mu, K_bend)

    def resid(dp):
        return sum(_m_from_dp(l, dp, *args) for l in legs) - m_total

    lo, hi = 1e-3, 1e3
    while resid(hi) < 0 and hi < 1e9:
        hi *= 10.0
    dp = brentq(resid, lo, hi, xtol=1e-9)

    rows = []
    for l in legs:
        m = _m_from_dp(l, dp, *args)
        D = p.tube.Di / 1000.0
        v = m / (rho * math.pi * D * D / 4.0)
        rows.append({"id": l.cid, "m_gs": m * 1000.0, "frac": m / m_total,
                     "v_ms": v, "Re": rho * v * D / mu,
                     "dp_kPa": dp / 1000.0, "L_path_mm": l.L_path,
                     "L_feed_mm": l.L_feed, "n_bend": l.n_bend})
    fr = [r["frac"] for r in rows]
    ideal = 1.0 / len(legs)
    return {"dp_Pa": dp, "rho": rho, "mu": mu, "rows": rows,
            "frac_min": min(fr), "frac_max": max(fr),
            "maldist_pct": (max(fr) - min(fr)) / ideal * 100.0,
            "worst_dev_pct": max(abs(f - ideal) for f in fr) / ideal * 100.0}


def size_jumps(legs: List[Leg], m_total: float, p: FTHXParams, pl: PlenumSpec,
               fl: Fluid, K_bend: float = 0.7) -> dict:
    """균등 분배를 만드는 porous jump C2 를 회로별로 산정.

    목표 유량 m* = m_total/C 에서 각 가지의 ΔP 를 구하고,
    가장 큰 값에 맞추도록 부족분을 관성 저항으로 채움:
        Δp_jump = C2 · ½ρv² · Δm    →    C2 = 2Δp_jump / (ρ v² Δm)
    """
    rho, mu = fl.props()
    args = (p, pl, rho, mu, K_bend)
    m_t = m_total / len(legs)
    base = [leg_dp(l, m_t, *args) for l in legs]
    dp_max = max(base)
    D = pl.D_feed / 1000.0
    v = m_t / (rho * math.pi * D * D / 4.0)
    dm = pl.jump_thick / 1000.0
    out = []
    for l, b in zip(legs, base):
        gap = dp_max - b
        C2 = 2.0 * gap / (rho * v * v * dm) if gap > 0 else 0.0
        l.jump_C2 = C2
        out.append({"id": l.cid, "dp_base_kPa": b / 1000.0,
                    "dp_jump_kPa": gap / 1000.0, "C2_1perm": C2})
    return {"m_target_gs": m_t * 1000.0, "v_feed_ms": v,
            "dp_target_kPa": dp_max / 1000.0, "jump_thick_mm": pl.jump_thick,
            "rows": out}


# ══════════════════════════════════════════════════════════════════
#  회로 → 가지
# ══════════════════════════════════════════════════════════════════
def legs_from_circuits(p: FTHXParams, cs: CQC.CircuitSet,
                       pl: PlenumSpec) -> List[Leg]:
    rep = CQC.build(p, cs)
    xy = CQC.tube_xy(p)
    z0, z1 = CQC.z_ends(p)
    inl = {q["circuit"]: q for q in rep["ports"] if q["kind"] == "inlet"}
    legs = []
    for c in rep["summary"]["circuits"]:
        q = inl[c["id"]]
        t = q["tube"]
        zp = (z0 - pl.offset) if q["end"] == "z0" else (z1 + pl.offset)
        xp = p.core_bbox[0] + pl.x_off
        L_feed = math.hypot(xy[t][0] - xp,
                            (z0 if q["end"] == "z0" else z1) - zp)
        legs.append(Leg(cid=c["id"], L_path=c["path_mm"],
                        n_bend=c["n_bend"], L_feed=L_feed))
    return legs


def entry_length(D_mm: float, m_kgs: float, rho: float, mu: float) -> dict:
    """수력학적 발달 길이.
       난류는 Bhatti&Shah  L_e/D = 4.4·Re^(1/6),  층류는 L_e/D = 0.05·Re."""
    D = D_mm / 1000.0
    A = math.pi * D * D / 4.0
    v = m_kgs / (rho * A)
    Re = rho * v * D / mu
    ratio = 4.4 * Re ** (1.0 / 6.0) if Re > 2300 else 0.05 * Re
    return {"D_mm": D_mm, "v_ms": v, "Re": Re,
            "Le_over_D": ratio, "Le_mm": ratio * D_mm,
            "regime": "turbulent" if Re > 2300 else "laminar"}


def stub_development(p: FTHXParams, pl: PlenumSpec, fl: Fluid,
                     m_total: float) -> dict:
    """입구 스터브가 발달 길이를 확보했는지. 스터브에는 총유량이 흐름."""
    rho, mu = fl.props()
    e = entry_length(pl.stub_dia(), m_total, rho, mu)
    need = e["Le_mm"]
    prac = 10.0 * pl.stub_dia()          # 실무 기준: 프로파일 95% 발달 ≈ 10D
    return {**e, "stub_len_mm": pl.stub_len,
            "Le_full_mm": round(need, 1), "Le_practical_mm": round(prac, 1),
            "developed_full": pl.stub_len >= need - 1e-9,
            "developed_practical": pl.stub_len >= prac - 1e-9,
            "fraction_full": (pl.stub_len / need) if need > 0 else 1.0,
            "criterion_note": "full = 4.4·Re^(1/6)·D (Bhatti&Shah), "
                              "practical = 10D (프로파일 95%)"}


# ══════════════════════════════════════════════════════════════════
#  간섭 검사 — 피더 · 플레넘 ↔ 벤드
# ══════════════════════════════════════════════════════════════════
def _feeder_polyline(p: FTHXParams, port: dict, pl: PlenumSpec,
                     n: int = 40) -> "np.ndarray":
    import numpy as np
    xy = CQC.tube_xy(p)
    z0, z1 = CQC.z_ends(p)
    t = port["tube"]
    zc = z0 if port["end"] == "z0" else z1
    sgn = -1.0 if port["end"] == "z0" else 1.0
    zz = np.linspace(zc, zc + sgn * pl.offset, n)
    return np.column_stack([np.full(n, xy[t][0]), np.full(n, xy[t][1]), zz])


def _plenum_groups(p: FTHXParams, ports, pl: PlenumSpec) -> dict:
    """(kind, end) 별 플레넘 축·반경. cad.build 와 동일한 규칙."""
    xy = CQC.tube_xy(p)
    z0, z1 = CQC.z_ends(p)
    out = {}
    by = {}
    for q in ports:
        by.setdefault((q["kind"], q["end"]), []).append(q)
    for (kind, end), lst in by.items():
        xs = [xy[q["tube"]][0] for q in lst]
        ys = [xy[q["tube"]][1] for q in lst]
        Dp = max(pl.D_plenum, (max(xs) - min(xs)) + pl.D_feed + 4.0)
        zc = z0 if end == "z0" else z1
        sgn = -1.0 if end == "z0" else 1.0
        out[(kind, end)] = {"x": sum(xs) / len(xs), "z": zc + sgn * pl.offset,
                            "D": Dp, "y0": min(ys) - Dp * 0.6, "y1": max(ys) + Dp * 0.6}
    return out


def check_clearances(p: FTHXParams, cs: "CQC.CircuitSet", pl: PlenumSpec,
                     clearance: float = 1.0) -> dict:
    """피더·플레넘과 벤드 사이 간섭을 검사.

    두 종류의 성격이 다름:
      · 플레넘 ↔ 벤드  → offset 을 늘리면 풀림 (해소 가능)
      · 피더   ↔ 벤드  → 피더가 관 끝~플레넘 전 구간을 지나므로 거리로 안 풀림.
                         해당 관을 입출구로 쓸 수 없음 → 회로를 바꿔야 함 (구조적)
    """
    import numpy as np
    rep = CQC.build(p, cs)
    bends = CQC.derive_bends(p, cs)
    resolve_standoff = CQC.resolve_standoff
    resolve_standoff(p, bends)
    ports = rep["ports"]
    polys = {id(b): CQC.bend_polyline(p, b) for b in bends}

    feeder_hits, plenum_hits = [], []
    thr_f = (p.tube.Do + pl.D_feed) / 2 + clearance

    for q in ports:
        F = _feeder_polyline(p, q, pl)
        for b in bends:
            if b.end != q["end"] or q["tube"] in (b.a, b.b):
                continue
            d = float(np.min(np.linalg.norm(F[:, None, :] - polys[id(b)][None, :, :], axis=2)))
            if d < thr_f:
                feeder_hits.append({"port": q["name"], "bend": f"{b.circuit}#{b.k}",
                                    "end": q["end"], "dist_mm": round(d, 2),
                                    "limit_mm": round(thr_f, 2)})

    groups = _plenum_groups(p, ports, pl)
    need = {}
    for (kind, end), g in groups.items():
        thr_p = g["D"] / 2 + p.tube.Do / 2 + clearance
        sgn = -1.0 if end == "z0" else 1.0
        for b in bends:
            if b.end != end:
                continue
            P = polys[id(b)]
            inside = (P[:, 1] >= g["y0"]) & (P[:, 1] <= g["y1"])
            if not inside.any():
                continue
            d = float(np.min(np.hypot(P[inside, 0] - g["x"], P[inside, 2] - g["z"])))
            if d < thr_p:
                plenum_hits.append({"plenum": f"{kind}_{end}", "bend": f"{b.circuit}#{b.k}",
                                    "dist_mm": round(d, 2), "limit_mm": round(thr_p, 2)})
            reach = float(np.max(sgn * (P[inside, 2] - (0.0 if end == "z0" else p.tube.L))))
            need[(kind, end)] = max(need.get((kind, end), 0.0), reach + thr_p)

    min_off = round(max(need.values()), 1) if need else 0.0
    return {"clearance_mm": clearance,
            "feeder_vs_bend": {"n": len(feeder_hits), "structural": True,
                               "hits": feeder_hits[:10]},
            "plenum_vs_bend": {"n": len(plenum_hits), "resolvable": True,
                               "hits": plenum_hits[:10]},
            "offset_mm": pl.offset, "min_offset_mm": min_off,
            "offset_ok": pl.offset >= min_off - 1e-9,
            "ok": not feeder_hits and not plenum_hits}
