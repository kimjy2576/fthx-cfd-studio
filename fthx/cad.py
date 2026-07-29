"""
FT-HX CAD 생성기 (CadQuery / OCC)

좌표계:  x = 공기 흐름 방향(열 방향)
         y = 횡방향 (관 적층 방향)
         z = 관 축 방향 (스팬)

바디 네이밍 규약 (Fluent Meshing 이 STEP product name 을 존 이름으로 승계):
    fluid_air_up            상류 연장
    fluid_air_core[_rNN]    핀 영역 = 포러스 존 (관 체적 제외됨)
    fluid_air_down          하류 연장
    solid_tube_rNNtMM       관 벽 (솔리드)
    fluid_ref_rNNtMM        관내 냉매 체적
    solid_bend_XXX          리턴 벤드
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cadquery as cq

from .params import FTHXParams
from . import circuits as CQC
from . import distributor as DST


def _box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def _cyl(r, x, y, z0, z1):
    return cq.Solid.makeCylinder(r, z1 - z0, cq.Vector(x, y, z0), cq.Vector(0, 0, 1))


def _half_torus(R, r, cx, cy, z, th, up: bool):
    """d 방향과 z 가 만드는 평면 안의 반원 파이프.
       회전축 n = d x z = (sin th, -cos th, 0) → 링 평면이 d,z 를 포함.
       위/아래 반쪽은 축정렬 박스와 교집합으로 잘라냄."""
    n = cq.Vector(math.sin(th), -math.cos(th), 0)
    tor = cq.Solid.makeTorus(R, r, cq.Vector(cx, cy, z), n)
    pad = R + r + 1.0
    z0 = z if up else z - pad
    box = cq.Solid.makeBox(2 * pad, 2 * pad, pad, cq.Vector(cx - pad, cy - pad, z0))
    return tor.intersect(box)


def build(p: FTHXParams, cs: "CQC.CircuitSet | None" = None,
          plenum: "DST.PlenumSpec | None" = None) -> tuple[cq.Assembly, dict]:
    t, f, d = p.tube, p.fin, p.domain
    x0, x1, y0, y1, z0, z1 = p.core_bbox      # 핀 팩(포러스 코어)
    dk = p.duct_box                            # 공기 도메인 단면(덕트)
    tz_lo, tz_hi = p.tube_z                   # 관 실제 범위
    centers = p.tube_centers()
    n_tube = t.Nr * t.Nt

    # 회로: 명시적으로 주면 그대로 존중(벤드 생성), 미지정이면 include_bends 를 따름
    explicit = cs is not None
    if cs is None:
        cs = CQC.gen_row_serpentine(p) if d.include_bends else CQC.CircuitSet(
            pattern="none",
            circuits=[CQC.Circuit(id=f"c{i+1:02d}", tubes=[i]) for i in range(n_tube)])
    rep = CQC.build(p, cs)
    bends = CQC.derive_bends(p, cs)
    CQC.resolve_standoff(p, bends)
    if not (d.include_bends or explicit):
        bends = []

    # 관은 자기 끝단에 붙은 벤드의 standoff 만큼만 연장 (벤드와 정확히 맞물림)
    e0 = [0.0] * n_tube
    e1 = [0.0] * n_tube
    for bd in bends:
        tgt = e1 if bd.end == "z1" else e0
        tgt[bd.a] = max(tgt[bd.a], bd.standoff)
        tgt[bd.b] = max(tgt[bd.b], bd.standoff)
    zr = [(tz_lo - e0[i], tz_hi + e1[i]) for i in range(n_tube)]
    tz0, tz1 = tz_lo - max(e0), tz_hi + max(e1)

    outer_by_row = {
        r: cq.Compound.makeCompound(
            [_cyl(t.Do / 2, x, y, *zr[rr * t.Nt + ii])
             for (rr, ii, x, y) in centers if rr == r])
        for r in range(t.Nr)}
    outer_all = cq.Compound.makeCompound(list(outer_by_row.values()))

    assy = cq.Assembly(name=p.name)

    # ---- 공기측 ----
    def _ext(xa, xb, tag, col):
        """상·하류 연장. 덕트 간극이 있으면 핀 팩 경계에서 쪼개
           코어열·바이패스열과 각각 conformal 하게 맞물리도록 함."""
        full = _box(xa, xb, dk["y0"], dk["y1"], dk["z0"], dk["z1"])
        if dk["sealed"]:
            assy.add(full, name=f"fluid_air_{tag}", color=col)
            return
        inner = _box(xa, xb, y0, y1, z0, z1)
        assy.add(inner, name=f"fluid_air_{tag}_core", color=col)
        assy.add(full.cut(inner), name=f"fluid_air_{tag}_bypass", color=col)

    if d.L_up > 0:
        _ext(x0 - d.L_up, x0, "up", cq.Color(0.6, 0.8, 1.0, 0.3))

    n_slab = t.Nr if d.split_core_by_row else 1
    sw = (x1 - x0) / n_slab
    for r in range(n_slab):
        xa, xb = x0 + r * sw, x0 + (r + 1) * sw
        cut = outer_by_row[r] if d.split_core_by_row else outer_all
        tag = f"_r{r+1:02d}" if d.split_core_by_row else ""
        fin_slab = _box(xa, xb, y0, y1, z0, z1)
        assy.add(fin_slab.cut(cut), name=f"fluid_air_core{tag}",
                 color=cq.Color(0.3, 0.9, 0.5, 0.35))
        if not dk["sealed"]:                       # 덕트 간극 = 바이패스 유로
            duct_slab = _box(xa, xb, dk["y0"], dk["y1"], dk["z0"], dk["z1"])
            byp = duct_slab.cut(_box(xa, xb, y0, y1, z0, z1)).cut(cut)
            assy.add(byp, name=f"fluid_air_bypass{tag}",
                     color=cq.Color(0.95, 0.85, 0.4, 0.35))

    if d.L_down > 0:
        _ext(x1, x1 + d.L_down, "down", cq.Color(1.0, 0.7, 0.5, 0.3))

    # ---- 관 ----
    for (r, i, x, y) in centers:
        tag = f"r{r+1:02d}t{i+1:02d}"
        a, b = zr[r * t.Nt + i]
        inner = _cyl(t.Di / 2, x, y, a, b)
        assy.add(_cyl(t.Do / 2, x, y, a, b).cut(inner), name=f"solid_tube_{tag}",
                 color=cq.Color(0.8, 0.5, 0.2))
        if d.include_tube_fluid:
            assy.add(inner, name=f"fluid_ref_{tag}", color=cq.Color(0.2, 0.4, 0.9))

    # ---- 리턴 벤드 (회로 기반, 임의 관 쌍) ----
    xy = {r * t.Nt + i: (x, y) for (r, i, x, y) in centers}
    for bd in bends:
        up = (bd.end == "z1")
        zs = (tz_hi + bd.standoff) if up else (tz_lo - bd.standoff)
        tag = f"{bd.circuit}_k{bd.k:02d}"
        th = math.atan2(xy[bd.b][1] - xy[bd.a][1], xy[bd.b][0] - xy[bd.a][0])
        o = _half_torus(bd.R, t.Do / 2, *bd.center_xy, zs, th, up)
        n = _half_torus(bd.R, t.Di / 2, *bd.center_xy, zs, th, up)
        assy.add(o.cut(n), name=f"solid_bend_{tag}", color=cq.Color(0.8, 0.5, 0.2))
        if d.include_tube_fluid:
            assy.add(n, name=f"fluid_bend_{tag}", color=cq.Color(0.2, 0.4, 0.9))

    # ---- 입구 플레넘 / 출구 헤더 + 피더 (다중 입출구 처리) ----
    plen_meta = None
    if plenum is not None:
        plen_meta = {"D_plenum_mm": plenum.D_plenum, "offset_mm": plenum.offset,
                     "D_feed_mm": plenum.D_feed, "jumps": [], "plenums": []}
        by = {}
        for prt in rep["ports"]:
            by.setdefault((prt["kind"], prt["end"]), []).append(prt)
        for (kind, end), lst in by.items():
            xs = [xy[q["tube"]][0] for q in lst]
            ys = [xy[q["tube"]][1] for q in lst]
            xp = sum(xs) / len(xs)
            zc = tz_lo if end == "z0" else tz_hi
            sgn = -1.0 if end == "z0" else 1.0
            zp = zc + sgn * plenum.offset
            Dp = max(plenum.D_plenum, (max(xs) - min(xs)) + plenum.D_feed + 4.0)
            ya, yb = min(ys) - Dp * 0.6, max(ys) + Dp * 0.6
            pl_solid = cq.Solid.makeCylinder(Dp / 2, yb - ya,
                          cq.Vector(xp, ya, zp), cq.Vector(0, 1, 0))
            pname = f"fluid_plenum_{'in' if kind=='inlet' else 'out'}_{end}"
            assy.add(pl_solid, name=pname, color=cq.Color(0.2, 0.4, 0.9))
            plen_meta["plenums"].append({
                "name": pname, "kind": kind, "end": end, "D_mm": Dp,
                "axis_x": xp, "z": zp, "y_range": [ya, yb],
                "main_port_seed": [xp, ya, zp],
                "main_port_name": f"ref_{'inlet' if kind=='inlet' else 'outlet'}_main_{end}"})

            clear = plenum.offset - Dp / 2                    # 플레넘 표면까지 여유
            sp = min(plenum.split_frac, 0.8) * max(clear, 1.0)
            for q in lst:
                cx_, cy_ = xy[q["tube"]]
                r_ = plenum.D_feed / 2
                a = cq.Solid.makeCylinder(r_, sp, cq.Vector(cx_, cy_, zc),
                                          cq.Vector(0, 0, sgn))
                b = cq.Solid.makeCylinder(r_, plenum.offset - sp,
                        cq.Vector(cx_, cy_, zc + sgn * sp), cq.Vector(0, 0, sgn))
                cid = q["circuit"]
                kk = "in" if kind == "inlet" else "out"
                assy.add(a, name=f"fluid_feed_{cid}_{kk}_a", color=cq.Color(0.3, 0.6, 0.95))
                assy.add(b.cut(pl_solid), name=f"fluid_feed_{cid}_{kk}_b",
                         color=cq.Color(0.3, 0.6, 0.95))
                if kind == "inlet":
                    plen_meta["jumps"].append({
                        "name": f"porous_jump_{cid}", "circuit": cid,
                        "between": [f"fluid_feed_{cid}_in_a", f"fluid_feed_{cid}_in_b"],
                        "seed": [cx_, cy_, zc + sgn * sp],
                        "thickness_mm": plenum.jump_thick})

    # ---- 메타데이터 (메시 저널이 좌표로 면을 집게 함) ----
    yc, zc = (dk["y0"] + dk["y1"]) / 2, (dk["z0"] + dk["z1"]) / 2
    meta = {
        "name": p.name,
        "units": "mm",
        "params": p.model_dump(),
        "derived": p.derived(),
        "ft_spec_SI": p.to_ft_spec(),
        "core_bbox": {"x": [x0, x1], "y": [y0, y1], "z": [z0, z1]},
        "fin_pack": p.fin_pack,
        "duct_box": dk,
        "tube_z": [tz_lo, tz_hi],
        "face_seeds": {
            "air_inlet":  [x0 - d.L_up, yc, zc],
            "air_outlet": [x1 + d.L_down, yc, zc],
            "duct_y_min": [(x0 + x1) / 2, dk["y0"], zc],
            "duct_y_max": [(x0 + x1) / 2, dk["y1"], zc],
            "duct_z_min": [(x0 + x1) / 2, yc, dk["z0"]],
            "duct_z_max": [(x0 + x1) / 2, yc, dk["z1"]],
        },
        "zone_prefix": {"fluid_air_": "fluid", "fluid_ref_": "fluid",
                        "solid_": "solid", "fluid_air_core": "porous"},
        "plenum": plen_meta,
        "circuits": {
            "pattern": cs.pattern,
            "list": [c.model_dump() for c in cs.circuits],
            "bends": [b.model_dump() for b in bends],
            "ports": rep["ports"],
            "validation": {"ok": rep["ok"], "warnings": rep["warnings"],
                           "standoff": rep["standoff"], "summary": rep["summary"]},
        },
    }
    for prt in rep["ports"]:
        meta["face_seeds"][prt["name"]] = prt["seed"]
    if plen_meta:
        for pm in plen_meta["plenums"]:
            meta["face_seeds"][pm["main_port_name"]] = pm["main_port_seed"]
        for j in plen_meta["jumps"]:
            meta["face_seeds"][j["name"]] = j["seed"]
    return assy, meta


def export(p: FTHXParams, outdir: str = "out", cs=None, plenum=None,
           fluid=None, m_total: float = 0.0) -> dict:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    assy, meta = build(p, cs, plenum)
    # 분배 예측 + porous jump 계수를 메타에 심음 (Fluent 저널이 그대로 읽음)
    if plenum is not None and fluid is not None and m_total > 0 and cs is not None:
        legs = DST.legs_from_circuits(p, cs, plenum)
        before = DST.solve_split(legs, m_total, p, plenum, fluid)
        jumps = DST.size_jumps(legs, m_total, p, plenum, fluid)
        after = DST.solve_split(legs, m_total, p, plenum, fluid)
        C2 = {r["id"]: r["C2_1perm"] for r in jumps["rows"]}
        for j in meta["plenum"]["jumps"]:
            j["C2_1perm"] = C2.get(j["circuit"], 0.0)
            j["alpha_perm_m2"] = None          # 관성항만 사용
        meta["plenum"]["distribution"] = {
            "fluid": fluid.name, "T_C": fluid.T_C, "quality": fluid.quality,
            "rho": before["rho"], "mu": before["mu"], "m_total_kgs": m_total,
            "before": {"maldist_pct": before["maldist_pct"], "rows": before["rows"]},
            "jump_sizing": jumps,
            "after": {"maldist_pct": after["maldist_pct"], "rows": after["rows"]}}
    step = out / f"{p.name}.step"
    assy.export(str(step))
    (out / f"{p.name}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    meta["_files"] = {"step": str(step), "json": str(out / f'{p.name}.json')}
    return meta


