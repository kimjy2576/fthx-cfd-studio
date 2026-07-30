"""
FT-HX 냉매 회로(circuit) 설계 — 1단계: 스키마 · 자동 생성기 · 검증

관 ID 는 flat int:  tid = r * Nt + i     (r = 열 index, i = 단 index)

회로 규칙
---------
입구 끝단(inlet_end)만 정하면 이후 벤드 끝단은 자동으로 교대함.
  inlet_end="z0" → 관1 은 z0 로 들어가 z1 로 나옴 → 벤드1 은 z1
  즉 k 번째 벤드(1-base)의 끝단은  k 홀수 → z1, 짝수 → z0   (inlet_end="z1" 이면 반대)

벤드 형상
---------
관 A,B 는 둘 다 z 축 평행. d = (B-A) 의 xy 성분, R = |d|/2.
반원 벤드는 d 와 z 가 만드는 평면 안에 놓임:
    반토러스(링=XY평면, 끝점 ±X, 볼록 +Y)
      → rotateX(±90°)  : 볼록을 ±z 로
      → rotateZ(atan2(dy,dx)) : 끝점을 d 방향으로
스탠드오프(standoff)는 코어 끝면에서 벤드를 z 로 더 밀어내는 직선 구간 길이임.
같은 끝단 벤드끼리 겹칠 때 단계적으로 밀어서 회피함(실제 코일의 long/short return bend).
"""
from __future__ import annotations

import itertools
import math
from typing import List, Literal, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field, model_validator

from .params import FTHXParams


# ══════════════════════════════════════════════════════════════════
#  스키마
# ══════════════════════════════════════════════════════════════════
class Circuit(BaseModel):
    id: str
    tubes: List[int] = Field(..., min_length=1, description="관 flat id, 냉매 진행 순서")
    inlet_end: Literal["z0", "z1"] = "z0"
    m_frac: Optional[float] = Field(None, ge=0, le=1, description="질량유량 분율(미지정=균등)")

    @model_validator(mode="after")
    def _unique(self):
        if len(set(self.tubes)) != len(self.tubes):
            raise ValueError(f"{self.id}: 같은 관을 두 번 지나감")
        return self


class CircuitSet(BaseModel):
    pattern: str = "custom"
    circuits: List[Circuit]

    @property
    def n(self) -> int:
        return len(self.circuits)


class Bend(BaseModel):
    circuit: str
    k: int                      # 회로 내 벤드 순번 (1-base)
    a: int
    b: int
    end: Literal["z0", "z1"]
    R: float                    # 중심선 반경
    span: float                 # 두 관 중심거리
    center_xy: Tuple[float, float]
    leg: float = 0.0            # 직선 다리 (설계 규격)
    straight: float = 0.0       # 두 원호 사이 직선 = span - 2R
    standoff: float = 0.0       # 간섭 회피용 추가 직선
    level: int = 0

    @property
    def straight_total(self) -> float:
        """관 끝에서 원호 시작까지 = 설계 다리 + 간섭 회피분"""
        return self.leg + self.standoff

    @property
    def protrusion(self) -> float:
        return self.straight_total + self.R

    @property
    def path_len(self) -> float:
        return 2.0 * self.straight_total + math.pi * self.R + self.straight


# ══════════════════════════════════════════════════════════════════
#  좌표 유틸
# ══════════════════════════════════════════════════════════════════
def tube_xy(p: FTHXParams) -> np.ndarray:
    """flat id 순서의 (x, y) 배열"""
    a = np.zeros((p.tube.Nr * p.tube.Nt, 2))
    for (r, i, x, y) in p.tube_centers():
        a[r * p.tube.Nt + i] = (x, y)
    return a


def rc(p: FTHXParams, tid: int) -> Tuple[int, int]:
    return divmod(tid, p.tube.Nt)


def z_ends(p: FTHXParams) -> Tuple[float, float]:
    """벤드가 붙는 곳 = 핀 팩 끝이 아니라 관 끝단."""
    return p.tube_z


# ══════════════════════════════════════════════════════════════════
#  자동 생성기
# ══════════════════════════════════════════════════════════════════
def _boustro(seq: Sequence[int], flip: bool) -> List[int]:
    return list(seq)[::-1] if flip else list(seq)


def gen_row_serpentine(p: FTHXParams, inlet_end: str = "z0") -> CircuitSet:
    """열별 사행 — 각 열이 독립 회로 (현재 GUI 기본값). 회로 = Nr 개"""
    Nt = p.tube.Nt
    cs = [Circuit(id=f"c{r+1:02d}", tubes=[r * Nt + i for i in range(Nt)],
                  inlet_end=inlet_end) for r in range(p.tube.Nr)]
    return CircuitSet(pattern="row_serpentine", circuits=cs)


def gen_face_split(p: FTHXParams, n_circuit: int, inlet_end: str = "z0") -> CircuitSet:
    """전면 N분할 — 단(i) 방향을 N개 밴드로 쪼개고, 각 회로가 모든 열을 사행 통과.
       공기와 대향류가 되도록 열 순서를 뒤에서 앞으로 감."""
    Nr, Nt = p.tube.Nr, p.tube.Nt
    if n_circuit > Nt:
        raise ValueError(f"회로 수({n_circuit})가 단수({Nt})보다 많음")
    edges = [round(Nt * c / n_circuit) for c in range(n_circuit + 1)]
    cs = []
    for c in range(n_circuit):
        band = range(edges[c], edges[c + 1])
        tubes = []
        for j, r in enumerate(reversed(range(Nr))):        # 뒤 열 → 앞 열 (대향류)
            tubes += [r * Nt + i for i in _boustro(band, j % 2 == 1)]
        cs.append(Circuit(id=f"c{c+1:02d}", tubes=tubes, inlet_end=inlet_end))
    return CircuitSet(pattern=f"face_split_{n_circuit}", circuits=cs)


def gen_interlaced(p: FTHXParams, n_circuit: int, inlet_end: str = "z0") -> CircuitSet:
    """인터레이스드 — 단 방향으로 stride N 로 건너뛰며 배정.
       공기 온도 성층(상·하 편차)을 회로마다 고르게 겪게 함.
       대가로 벤드 span 이 N·Pt 까지 커짐 → 검증에서 경고가 뜰 수 있음."""
    Nr, Nt = p.tube.Nr, p.tube.Nt
    cs = []
    for c in range(n_circuit):
        band = list(range(c, Nt, n_circuit))
        tubes = []
        for j, r in enumerate(reversed(range(Nr))):
            tubes += [r * Nt + i for i in _boustro(band, j % 2 == 1)]
        cs.append(Circuit(id=f"c{c+1:02d}", tubes=tubes, inlet_end=inlet_end))
    return CircuitSet(pattern=f"interlaced_{n_circuit}", circuits=cs)


def gen_single(p: FTHXParams, inlet_end: str = "z0") -> CircuitSet:
    """단일 회로 — 전체를 하나로 (소형 코일)"""
    Nr, Nt = p.tube.Nr, p.tube.Nt
    tubes = []
    for j, r in enumerate(reversed(range(Nr))):
        tubes += [r * Nt + i for i in _boustro(range(Nt), j % 2 == 1)]
    return CircuitSet(pattern="single", circuits=[
        Circuit(id="c01", tubes=tubes, inlet_end=inlet_end)])


GENERATORS = {"row_serpentine": gen_row_serpentine, "face_split": gen_face_split,
              "interlaced": gen_interlaced, "single": gen_single}


# ══════════════════════════════════════════════════════════════════
#  벤드 도출
# ══════════════════════════════════════════════════════════════════
def derive_bends(p: FTHXParams, cs: CircuitSet) -> List[Bend]:
    xy = tube_xy(p)
    out: List[Bend] = []
    for ck in cs.circuits:
        for k, (a, b) in enumerate(zip(ck.tubes, ck.tubes[1:]), start=1):
            odd = (k % 2 == 1)
            end = ("z1" if odd else "z0") if ck.inlet_end == "z0" else ("z0" if odd else "z1")
            d = xy[b] - xy[a]
            span = float(np.hypot(*d))
            R = p.bend.radius(span, p.tube.Do)
            out.append(Bend(circuit=ck.id, k=k, a=a, b=b, end=end, R=R,
                            span=span, center_xy=tuple((xy[a] + xy[b]) / 2),
                            leg=p.bend.leg, straight=span - 2.0 * R))
    return out


def io_ports(p: FTHXParams, cs: CircuitSet) -> List[dict]:
    """회로별 입·출구 포트 (Fluent 경계 이름 + face seed 좌표).
       port_stub 만큼 관이 연장되면 경계면도 그만큼 밀려남."""
    xy, (z0, z1) = tube_xy(p), z_ends(p)
    ps = p.domain.port_stub
    z0, z1 = z0 - ps, z1 + ps
    ports = []
    for ck in cs.circuits:
        n = len(ck.tubes)
        in_end = ck.inlet_end
        # n개 관을 지나면 끝단이 n-1번 바뀜
        out_end = in_end if (n - 1) % 2 == 0 else ("z1" if in_end == "z0" else "z0")
        for kind, tid, e in (("inlet", ck.tubes[0], in_end),
                             ("outlet", ck.tubes[-1], out_end)):
            ports.append({"name": f"ref_{kind}_{ck.id}", "circuit": ck.id, "kind": kind,
                          "tube": tid, "rc": rc(p, tid), "end": e,
                          "seed": [float(xy[tid][0]), float(xy[tid][1]),
                                   z0 if e == "z0" else z1]})
    return ports


# ══════════════════════════════════════════════════════════════════
#  검증 1 — 위상
# ══════════════════════════════════════════════════════════════════
def validate_topology(p: FTHXParams, cs: CircuitSet,
                      max_span_factor: float = 2.5) -> List[str]:
    n_tube = p.tube.Nr * p.tube.Nt
    xy = tube_xy(p)
    msgs: List[str] = []

    seen: dict[int, str] = {}
    for ck in cs.circuits:
        for t in ck.tubes:
            if not (0 <= t < n_tube):
                msgs.append(f"{ck.id}: 관 id {t} 가 범위 밖 (0~{n_tube-1})")
            elif t in seen:
                msgs.append(f"관 {rc(p,t)} 이 {seen[t]} 와 {ck.id} 에 중복 배정됨")
            else:
                seen[t] = ck.id

    miss = sorted(set(range(n_tube)) - set(seen))
    if miss:
        msgs.append(f"미배정 관 {len(miss)}개: "
                    + ", ".join(str(rc(p, t)) for t in miss[:8])
                    + (" …" if len(miss) > 8 else ""))

    lim = max_span_factor * max(p.tube.Pt, p.tube.Pl)
    for bd in derive_bends(p, cs):
        if bd.span > lim:
            msgs.append(f"{bd.circuit} 벤드#{bd.k} span {bd.span:.1f}mm "
                        f"> 한계 {lim:.1f}mm — 제작성 확인 필요")
        if bd.span < p.tube.Do:
            msgs.append(f"{bd.circuit} 벤드#{bd.k} span {bd.span:.1f}mm < Do — 형상 불가")

    tot = sum(ck.m_frac for ck in cs.circuits if ck.m_frac is not None)
    if any(ck.m_frac is not None for ck in cs.circuits) and abs(tot - 1) > 1e-6:
        msgs.append(f"m_frac 합이 {tot:.4f} — 1.0 이어야 함")
    return msgs


# ══════════════════════════════════════════════════════════════════
#  검증 2 — 벤드 간섭 · 스탠드오프 배정
# ══════════════════════════════════════════════════════════════════
def bend_polyline(p: FTHXParams, bd: Bend, n_arc: int = 17) -> np.ndarray:
    """벤드 중심선 폴리라인.
       국소 평면 (u = 두 관을 잇는 방향, v = 관 축 바깥 방향) 에서 그린 뒤 회전·이동.
         다리 → 90° 원호 → 직선 → 90° 원호 → 다리
       R = span/2 면 직선이 사라져 반원이 됨.
    """
    xy, (z0, z1) = tube_xy(p), z_ends(p)
    A, B = xy[bd.a], xy[bd.b]
    sgn = 1.0 if bd.end == "z1" else -1.0
    ze = z1 if bd.end == "z1" else z0
    S, R, T = bd.span, bd.R, bd.straight_total
    th = math.atan2(B[1] - A[1], B[0] - A[0])

    uv: List[Tuple[float, float]] = []
    ns = max(2, int(T / 2.0) + 2)
    for j in range(ns):                                   # 다리 (A쪽)
        uv.append((-S / 2, T * j / (ns - 1)))
    for j in range(n_arc):                                # 원호 1 : 180° → 90°
        a = math.pi * (1.0 - 0.5 * j / (n_arc - 1))
        uv.append((-S / 2 + R + R * math.cos(a), T + R * math.sin(a)))
    if bd.straight > 1e-9:                                # 두 원호 사이 직선
        for j in range(1, 5):
            uv.append((-S / 2 + R + bd.straight * j / 4.0, T + R))
    for j in range(n_arc):                                # 원호 2 : 90° → 0°
        a = math.pi / 2 * (1.0 - j / (n_arc - 1))
        uv.append((S / 2 - R + R * math.cos(a), T + R * math.sin(a)))
    for j in range(ns):                                   # 다리 (B쪽)
        uv.append((S / 2, T * (1.0 - j / (ns - 1))))

    ct, st = math.cos(th), math.sin(th)
    return np.array([[bd.center_xy[0] + u * ct,
                      bd.center_xy[1] + u * st,
                      ze + sgn * v] for u, v in uv])


def _min_dist(P: np.ndarray, Q: np.ndarray) -> float:
    return float(np.min(np.linalg.norm(P[:, None, :] - Q[None, :, :], axis=2)))


def resolve_standoff(p: FTHXParams, bends: List[Bend], clearance: float = 1.0,
                     step: Optional[float] = None,
                     max_standoff: Optional[float] = None) -> dict:
    """같은 끝단 벤드끼리 겹치지 않도록 standoff 단계를 그리디 배정.

    z 로 밀어서 해소되는 '근접' 과, 아무리 밀어도 남는 '구조적 교차' 를 구분함.
    교차는 한 벤드의 호가 다른 벤드가 쓰는 관 바로 위를 지날 때 생기며,
    바깥 벤드의 직선 스텁이 안쪽 호를 반드시 관통하므로 z 이동으로는 못 푼다.
    → 회로를 바꾸거나, 꺾인(jogged) 벤드 모델이 필요함.
    """
    step = step or p.tube.Do * 1.6
    max_standoff = max_standoff if max_standoff is not None else 3.0 * p.tube.Pt
    n_lv = max(1, int(max_standoff / step))
    thr = p.tube.Do + clearance
    placed: dict = {"z0": [], "z1": []}
    crossings: List[dict] = []
    resolved = 0

    for bd in sorted(bends, key=lambda b: -b.R):
        hit: List[str] = []
        for lv in range(n_lv + 1):
            bd.level, bd.standoff = lv, lv * step
            poly = bend_polyline(p, bd)
            hit = [f"{o.circuit}#{o.k}" for o, q in placed[bd.end]
                   if _min_dist(poly, q) < thr]
            if not hit:
                if lv > 0:
                    resolved += 1
                placed[bd.end].append((bd, poly))
                break
        else:
            bd.level, bd.standoff = 0, 0.0          # 되돌림 (허위 배치 방지)
            crossings.append({"bend": f"{bd.circuit}#{bd.k}", "end": bd.end,
                              "span_mm": round(bd.span, 1), "conflicts_with": hit})
            placed[bd.end].append((bd, bend_polyline(p, bd)))

    lv = [b.level for b in bends]
    return {"step_mm": round(step, 2), "clearance_mm": clearance,
            "max_standoff_mm": round(max_standoff, 1),
            "levels_used": sorted(set(lv)), "max_level": max(lv) if lv else 0,
            "n_resolved_by_standoff": resolved,
            "n_structural_crossing": len(crossings),
            "crossings": crossings[:12],
            "max_protrusion_mm": round(max((b.protrusion for b in bends), default=0.0), 1)}


# ══════════════════════════════════════════════════════════════════
#  요약
# ══════════════════════════════════════════════════════════════════
def summarize(p: FTHXParams, cs: CircuitSet, bends: List[Bend]) -> dict:
    (z0, z1) = z_ends(p)
    Ls = z1 - z0
    A = math.pi * p.tube.Di ** 2 / 4
    rows = []
    for ck in cs.circuits:
        bs = [b for b in bends if b.circuit == ck.id]
        path = len(ck.tubes) * Ls + sum(b.path_len for b in bs)
        rows.append({"id": ck.id, "n_tube": len(ck.tubes), "n_bend": len(bs),
                     "path_mm": path, "V_mm3": path * A,
                     "rows_touched": sorted({rc(p, t)[0] for t in ck.tubes})})
    L = np.array([r["path_mm"] for r in rows])
    return {"pattern": cs.pattern, "n_circuit": cs.n, "circuits": rows,
            "path_mean_mm": float(L.mean()),
            "path_spread_pct": float((L.max() - L.min()) / L.mean() * 100),
            "V_total_cm3": float(sum(r["V_mm3"] for r in rows) / 1000)}


def build(p: FTHXParams, cs: CircuitSet, **kw) -> dict:
    """검증 + 스탠드오프 배정 + 요약을 한 번에"""
    msgs = validate_topology(p, cs)
    bends = derive_bends(p, cs)
    so = resolve_standoff(p, bends, **kw)
    return {"ok": not msgs and so["n_structural_crossing"] == 0,
            "warnings": msgs, "standoff": so,
            "summary": summarize(p, cs, bends),
            "ports": io_ports(p, cs),
            "bends": [b.model_dump() for b in bends]}


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════
def export(p: FTHXParams, cs: CircuitSet, path: str) -> dict:
    """회로 정의 + 검증 결과 + 벤드/포트를 JSON 으로. 2·3단계가 이 파일을 먹음."""
    import json
    from pathlib import Path
    r = build(p, cs)
    doc = {"schema": "fthx-circuits/1", "coil": p.to_ft_spec(),
           "tube_L_mm": p.tube.L, "layout": p.tube.layout,
           "circuits": cs.model_dump(), **r}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return doc


