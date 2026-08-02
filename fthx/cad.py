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

import dataclasses
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


def _bend_solid(bd, r: float, up: bool):
    """리턴 벤드 솔리드 — 다리 + 90°원호 + 직선 + 90°원호 + 다리.

    국소 프레임(u=+X: 두 관을 잇는 방향, v=+Z: 관 축 바깥)에서 축정렬로 만든 뒤
      (아래쪽 끝단이면 X축 180° 회전) → Z축 θ 회전 → 이동
    으로 배치함. 모든 불리언이 축정렬이라 안정적임.
    """
    S, R, T, St = bd.span, bd.R, bd.straight_total, bd.straight
    pad = R + r + 1.0
    parts = []

    if T > 1e-9:                                   # 직선 다리 2개
        for u in (-S / 2, S / 2):
            parts.append(cq.Solid.makeCylinder(r, T, cq.Vector(u, 0, 0),
                                               cq.Vector(0, 0, 1)))
    for sign in (-1, 1):                           # 90° 원호 2개
        uc = sign * (S / 2 - R) if sign > 0 else -(S / 2 - R)
        tor = cq.Solid.makeTorus(R, r, cq.Vector(uc, 0, T), cq.Vector(0, 1, 0))
        bx = (cq.Solid.makeBox(pad, 2 * pad, pad, cq.Vector(uc - pad, -pad, T))
              if sign < 0 else
              cq.Solid.makeBox(pad, 2 * pad, pad, cq.Vector(uc, -pad, T)))
        parts.append(tor.intersect(bx))
    if St > 1e-9:                                  # 두 원호 사이 직선
        parts.append(cq.Solid.makeCylinder(r, St, cq.Vector(-S / 2 + R, 0, T + R),
                                           cq.Vector(1, 0, 0)))
    out = parts[0]
    for q in parts[1:]:
        out = out.fuse(q)
    out = out.clean()
    if not up:                                     # 아래쪽 끝단
        out = out.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 180)
    return out


def _place_bend(solid, th_rad: float, cx: float, cy: float, ze: float):
    """국소 프레임 → θ 회전 → (cx, cy, ze) 이동"""
    return (solid.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1),
                         math.degrees(th_rad))
                 .translate(cq.Vector(cx, cy, ze)))


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
    # 냉매 입·출구 관 연장 (경계조건을 코일에서 떼고 발달 구간 확보)
    ps = d.port_stub
    if d.port_stub_auto:
        _rho, _mu = DST.Fluid(p.operating.ref.fluid,
                              p.operating.ref.T_sat_in, 1.0).props()
        _nc = max(1, len(cs.circuits))
        _e = DST.entry_length(t.Di, p.operating.ref.m_total / _nc, _rho, _mu)
        _need = _e["Le_mm"] if d.port_stub_criterion == "full" else 10.0 * t.Di
        ps = max(ps, math.ceil(_need))
    if ps > 0:
        for prt in rep["ports"]:
            tgt = e1 if prt["end"] == "z1" else e0
            tgt[prt["tube"]] = max(tgt[prt["tube"]], ps)
    # seed 는 절대값으로 덮어씀 (io_ports 는 선언값만 알고 자동 해소값을 모름)
    for prt in rep["ports"]:
        prt["seed"][2] = (tz_lo - ps) if prt["end"] == "z0" else (tz_hi + ps)

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
        ze = tz_hi if up else tz_lo
        th = math.atan2(xy[bd.b][1] - xy[bd.a][1], xy[bd.b][0] - xy[bd.a][0])
        tag = f"{bd.circuit}_k{bd.k:02d}"
        o = _place_bend(_bend_solid(bd, t.Do / 2, up), th, *bd.center_xy, ze)
        n = _place_bend(_bend_solid(bd, t.Di / 2, up), th, *bd.center_xy, ze)
        assy.add(o.cut(n), name=f"solid_bend_{tag}", color=cq.Color(0.8, 0.5, 0.2))
        if d.include_tube_fluid:
            assy.add(n, name=f"fluid_bend_{tag}", color=cq.Color(0.2, 0.4, 0.9))

    # ---- 입구 플레넘 / 출구 헤더 + 피더 (다중 입출구 처리) ----
    plen_meta = None
    if plenum is not None and not explicit and not d.include_bends:
        raise ValueError(
            f"리턴 벤드가 없어 관 {n_tube}개가 각각 독립 회로가 됨 → 포트 {2*n_tube}개·"
            f"피더 {2*n_tube}개가 생성됨. 회로(CircuitSet)를 지정하거나 "
            f"include_bends=True 로 둘 것")
    if plenum is not None:
        if plenum.stub_auto:
            _dv = DST.stub_development(p, plenum, DST.Fluid(),
                                       p.operating.ref.m_total)
            _need = (_dv["Le_full_mm"] if plenum.stub_criterion == "full"
                     else _dv["Le_practical_mm"])
            if plenum.stub_len < _need:
                plenum = dataclasses.replace(plenum, stub_len=math.ceil(_need))
        clr = DST.check_clearances(p, cs, plenum)
        if plenum.auto_offset and not clr["offset_ok"]:
            plenum = dataclasses.replace(plenum, offset=clr["min_offset_mm"] + 2.0)
            clr = DST.check_clearances(p, cs, plenum)
        plen_meta = {"D_plenum_mm": plenum.D_plenum, "offset_mm": plenum.offset,
                     "D_feed_mm": plenum.D_feed, "clearance": clr,
                     "stub_development": DST.stub_development(
                         p, plenum, DST.Fluid(p.operating.ref.fluid,
                                              p.operating.ref.T_sat_in, 1.0),
                         p.operating.ref.m_total),
                     "jumps": [], "plenums": []}
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
            kk0 = "in" if kind == "inlet" else "out"
            pname = f"fluid_plenum_{kk0}_{end}"
            assy.add(pl_solid, name=pname, color=cq.Color(0.2, 0.4, 0.9))

            # 입구 발달 스터브: 플레넘 축(-y)으로 연장. 별도 바디로 두어
            # 매니폴드 진입 프로파일을 따로 확인할 수 있게 함.
            port_y = ya
            if plenum.stub_len > 0:
                Ds = plenum.stub_dia()
                stub = cq.Solid.makeCylinder(
                    Ds / 2, plenum.stub_len,
                    cq.Vector(xp, ya - plenum.stub_len, zp), cq.Vector(0, 1, 0))
                if Ds > Dp:                     # 스터브가 더 굵으면 플레넘을 파냄
                    stub = stub.cut(pl_solid)
                assy.add(stub, name=f"fluid_stub_{kk0}_{end}",
                         color=cq.Color(0.35, 0.55, 0.95))
                port_y = ya - plenum.stub_len
            plen_meta["plenums"].append({
                "name": pname, "kind": kind, "end": end, "D_mm": Dp,
                "axis_x": xp, "z": zp, "y_range": [ya, yb],
                "stub_len_mm": plenum.stub_len,
                "stub_D_mm": plenum.stub_dia() if plenum.stub_len > 0 else None,
                "main_port_seed": [xp, port_y, zp],
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

    # ---- 케이싱 (공기 도메인을 감싸는 솔리드) ----
    # Fluent 은 인접 관계가 같은 면을 한 존으로 묶음. 케이싱이 없으면
    # 상·하류 박스의 자유면(입구+측벽4)이 한 덩어리가 되어 입구를 특정할 수 없음.
    # 케이싱을 두면 측벽이 계면이 되고 입구/출구만 자유면으로 남음.
    if p.duct.wall_t > 0:
        w = p.duct.wall_t
        # 공기 도메인 구간에 맞춰 분할 — 각 구간이 해당 공기 바디와
        # 정확히 일치하는 면을 갖게 되어 imprint 없이 계면이 성립함
        segs = []
        if d.L_up > 0:
            segs.append(("up", x0 - d.L_up, x0))
        segs.append(("core", x0, x1))
        if d.L_down > 0:
            segs.append(("down", x1, x1 + d.L_down))
        for tag, a, b_ in segs:
            inner = _box(a, b_, dk["y0"], dk["y1"], dk["z0"], dk["z1"])
            outer = _box(a, b_, dk["y0"] - w, dk["y1"] + w,
                         dk["z0"] - w, dk["z1"] + w)
            body = outer.cut(inner)
            # 관은 핀 팩 밖으로 나가므로 케이싱 벽(z 방향)을 뚫고 지나감.
            # 빼주지 않으면 체적이 겹쳐 tet 초기화가 실패함
            # (실측: "tet initialization failed ... intersections")
            body = body.cut(outer_all)
            if d.include_tube_fluid:
                body = body.cut(cq.Compound.makeCompound(
                    [_cyl(t.Di / 2, x, y, *zr[r_ * t.Nt + i_])
                     for (r_, i_, x, y) in centers]))
            if bends:
                for bd in bends:
                    up = (bd.end == "z1")
                    ze = tz_hi if up else tz_lo
                    th = math.atan2(xy[bd.b][1] - xy[bd.a][1],
                                    xy[bd.b][0] - xy[bd.a][0])
                    body = body.cut(_place_bend(
                        _bend_solid(bd, t.Do / 2, up), th, *bd.center_xy, ze))
            assy.add(body, name=f"solid_casing_{tag}",
                     color=cq.Color(0.6, 0.6, 0.62))

    # ---- z 대칭 반쪽 모델 ----
    if p.sym_z is not None:
        zc = p.sym_z
        big = 1e5
        keep = cq.Solid.makeBox(2 * big, 2 * big, big,
                                cq.Vector(-big, -big, zc))      # z >= zc 만 남김
        for ch in list(assy.children):
            cut = ch.obj.intersect(keep)
            if not cut.Solids():
                assy.children.remove(ch)
                assy.objects.pop(ch.name, None)
            else:
                ch.obj = cut
        meta_sym = {"plane": "z", "z": zc,
                    "seed": [(x0 + x1) / 2, (dk["y0"] + dk["y1"]) / 2, zc]}
    else:
        meta_sym = None

    # ---- 메타데이터 (메시 저널이 좌표로 면을 집게 함) ----
    yc, zc = (dk["y0"] + dk["y1"]) / 2, (dk["z0"] + dk["z1"]) / 2
    meta = {
        "schema_version": p.schema_version,
        "name": p.name,
        "units": "mm",
        "operating": p.operating.model_dump(),
        "operating_derived": p.operating_derived(),
        "params": p.model_dump(),
        "derived": p.derived(),
        "ft_spec_SI": p.to_ft_spec(),
        "core_bbox": {"x": [x0, x1], "y": [y0, y1], "z": [z0, z1]},
        "fin_pack": p.fin_pack,
        "symmetry": meta_sym,
        "duct_box": dk,
        "tube_z": [tz_lo, tz_hi],
        "port_stub": {
            "len_mm": ps,
            **(lambda rho_mu: {
                "per_circuit_kgs": p.operating.ref.m_total / max(1, len(cs.circuits)),
                **DST.entry_length(t.Di,
                    p.operating.ref.m_total / max(1, len(cs.circuits)),
                    *rho_mu),
                "Le_practical_mm": round(10.0 * t.Di, 1),
            })(DST.Fluid(p.operating.ref.fluid,
                         p.operating.ref.T_sat_in, 1.0).props())},
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
    if meta_sym:
        meta["face_seeds"]["symmetry_z"] = meta_sym["seed"]
    for prt in rep["ports"]:
        meta["face_seeds"][prt["name"]] = prt["seed"]
    if plen_meta:
        for pm in plen_meta["plenums"]:
            meta["face_seeds"][pm["main_port_name"]] = pm["main_port_seed"]
        for j in plen_meta["jumps"]:
            meta["face_seeds"][j["name"]] = j["seed"]
    return assy, meta


def check_overlap(assy, tol: float = 1e-6) -> list:
    """바디 간 체적 겹침 검사.

    겹치면 Fluent 볼륨 메싱이 실패함:
      "tet initialization failed possibly due to duplicate nodes/faces
       or intersections"
    표면 메시까지는 통과하므로 이 검사가 없으면 30분 뒤에야 알게 됨.
    """
    import itertools
    B = {}
    for c in assy.children:
        B[c.name] = c.obj
    out = []
    for a, b in itertools.combinations(sorted(B), 2):
        A, Bo = B[a], B[b]
        ba, bb = A.BoundingBox(), Bo.BoundingBox()
        if (ba.xmax < bb.xmin - tol or bb.xmax < ba.xmin - tol or
                ba.ymax < bb.ymin - tol or bb.ymax < ba.ymin - tol or
                ba.zmax < bb.zmin - tol or bb.zmax < ba.zmin - tol):
            continue
        try:
            v = A.intersect(Bo).Volume()
        except Exception:                                    # noqa: BLE001
            continue
        if v > tol:
            out.append({"a": a, "b": b, "volume_mm3": v})
    return out


def export(p: FTHXParams, outdir: str = "out", cs=None, plenum=None,
           fluid=None, m_total: float = 0.0) -> dict:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    assy, meta = build(p, cs, plenum)
    ov = check_overlap(assy)
    meta["overlap"] = ov
    if ov:
        raise ValueError(
            "바디 체적이 겹침 — Fluent 볼륨 메싱이 실패함:\n  "
            + "\n  ".join(f"{o['a']} ∩ {o['b']} = {o['volume_mm3']:,.2f} mm³"
                          for o in ov[:8]))
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
    ex = p.export
    assy.export(str(step), exportType="STEP", unit=ex.unit,
                write_pcurves=ex.write_pcurves, precision_mode=ex.precision_mode)
    (out / f"{p.name}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    meta["_files"] = {"step": str(step), "json": str(out / f'{p.name}.json')}
    return meta


