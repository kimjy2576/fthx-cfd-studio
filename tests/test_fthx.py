"""
검증 스위트 — 개발 중 수행한 확인들을 그대로 회귀 테스트로 고정.

    pytest -q                    (cadquery 없으면 형상 테스트는 자동 skip)
"""
import math
from pathlib import Path

import pytest

from fthx import FTHXParams, circuits as CQC, distributor as DST

try:
    import cadquery  # noqa: F401
    from fthx import cad as CAD
    HAS_CAD = True
except Exception:
    HAS_CAD = False

needs_cad = pytest.mark.skipif(not HAS_CAD, reason="cadquery 필요")
needs_cp = pytest.mark.skipif(not DST.HAS_CP, reason="CoolProp 필요")


@pytest.fixture
def p():
    return FTHXParams()


# ─────────────────────────── 파라미터 · 파생량 ───────────────────────────
def test_derived_matches_reference(p):
    """Wang 정의 파생량 기준값 (GUI 의 JS 구현과 일치해야 하는 값).
       공기측은 핀 칼라 직경 D_c = Do + 2·t_f 기준.
       존 체적은 CAD 가 Do 로 잘라내므로 Do 기준 유지."""
    d = p.derived()
    assert d["D_c_mm"] == pytest.approx(9.75, abs=1e-9)
    assert d["porosity_gamma"] == pytest.approx(0.9303675826, abs=1e-9)
    assert d["sigma"] == pytest.approx(0.5915539370, abs=1e-9)
    assert d["a_v_1perm"] == pytest.approx(1148.667003, abs=1e-5)
    assert d["D_h_mm"] == pytest.approx(2.3469694164, abs=1e-9)
    assert d["N_fin"] == 275
    assert d["V_collar_mm3"] == pytest.approx(83543.1168, rel=1e-9)


def test_invalid_geometry_rejected():
    with pytest.raises(ValueError):
        FTHXParams(tube={"Do": 9.52, "Di": 9.6})          # Di >= Do
    with pytest.raises(ValueError):
        FTHXParams(tube={"Pt": 9.0})                      # Pt <= Do
    with pytest.raises(ValueError):
        FTHXParams(fin={"FPI": 200, "t_f": 0.5})          # 핀 겹침


def test_ft_spec_roundtrip(p):
    spec = p.to_ft_spec()
    assert FTHXParams.from_ft_spec(spec, L_mm=p.tube.L).to_ft_spec() == spec


# ─────────────────────────── 회로 ───────────────────────────
@pytest.mark.parametrize("gen,n,ok", [
    ("single", None, True), ("row_serpentine", None, True),
    ("face_split", 4, True), ("face_split", 6, True),
    ("interlaced", 4, False),          # 구조적 교차 → 불가로 잡혀야 함
])
def test_patterns(p, gen, n, ok):
    cs = CQC.GENERATORS[gen](p, n) if n else CQC.GENERATORS[gen](p)
    assert CQC.build(p, cs)["ok"] is ok


def test_all_tubes_assigned_once(p):
    cs = CQC.gen_face_split(p, 4)
    seen = [t for c in cs.circuits for t in c.tubes]
    assert sorted(seen) == list(range(p.tube.Nr * p.tube.Nt))


def test_duplicate_tube_rejected():
    with pytest.raises(ValueError):
        CQC.Circuit(id="c", tubes=[0, 1, 0])


def test_topology_catches_overlap_and_gap(p):
    bad = CQC.CircuitSet(circuits=[CQC.Circuit(id="c01", tubes=[0, 1, 2, 3]),
                                   CQC.Circuit(id="c02", tubes=[3, 4, 5])])
    msgs = CQC.validate_topology(p, bad)
    assert any("중복" in m for m in msgs)
    assert any("미배정" in m for m in msgs)


def test_crossing_detected_but_nesting_allowed(p):
    """0→2 와 1→3 은 z 로 밀어도 안 풀리는 교차.
       0→5,1→4,2→3 동심 네스팅은 제작 가능하므로 통과해야 함."""
    cross = CQC.CircuitSet(circuits=[CQC.Circuit(id="cA", tubes=[0, 2]),
                                     CQC.Circuit(id="cB", tubes=[1, 3])])
    assert CQC.resolve_standoff(p, CQC.derive_bends(p, cross))["n_structural_crossing"] >= 1

    nest = CQC.CircuitSet(circuits=[CQC.Circuit(id="cN", tubes=[0, 5, 1, 4, 2, 3])])
    assert CQC.resolve_standoff(p, CQC.derive_bends(p, nest))["n_structural_crossing"] == 0


def test_bend_ends_alternate(p):
    cs = CQC.CircuitSet(circuits=[CQC.Circuit(id="c", tubes=[0, 1, 2, 3], inlet_end="z0")])
    assert [b.end for b in CQC.derive_bends(p, cs)] == ["z1", "z0", "z1"]


def test_ports_counterflow(p):
    """전면 N분할은 뒤 열에서 들어와 앞 열로 나가야 함(대향류)"""
    cs = CQC.gen_face_split(p, 4)
    ports = CQC.io_ports(p, cs)
    assert len(ports) == 2 * len(cs.circuits)
    ins = [q for q in ports if q["kind"] == "inlet"]
    outs = [q for q in ports if q["kind"] == "outlet"]
    assert all(q["rc"][0] == p.tube.Nr - 1 for q in ins)
    assert all(q["rc"][0] == 0 for q in outs)


# ─────────────────────────── 분배 ───────────────────────────
@needs_cp
def test_split_equal_for_identical_circuits(p):
    cs, pl = CQC.gen_face_split(p, 4), DST.PlenumSpec()
    r = DST.solve_split(DST.legs_from_circuits(p, cs, pl), 0.03, p, pl, DST.Fluid())
    assert r["maldist_pct"] == pytest.approx(0.0, abs=1e-9)


@needs_cp
def test_jumps_equalize_and_conserve_mass(p):
    cs, pl, fl = CQC.gen_face_split(p, 5), DST.PlenumSpec(), DST.Fluid()
    legs = DST.legs_from_circuits(p, cs, pl)
    before = DST.solve_split(legs, 0.03, p, pl, fl)
    assert before["maldist_pct"] > 5.0                 # 밴드가 불균등하므로 편차 발생
    DST.size_jumps(legs, 0.03, p, pl, fl)
    after = DST.solve_split(legs, 0.03, p, pl, fl)
    assert after["maldist_pct"] == pytest.approx(0.0, abs=1e-6)
    assert sum(r["m_gs"] for r in after["rows"]) == pytest.approx(30.0, rel=1e-9)


def test_churchill_limits():
    assert DST.churchill_f(100.0) == pytest.approx(64.0 / 100.0, rel=2e-2)   # 층류
    assert 0.015 < DST.churchill_f(1e5) < 0.025                              # 난류


# ─────────────────────────── 형상 ───────────────────────────
@needs_cad
def test_core_volume_matches_analytic(p):
    assy, meta = CAD.build(p)
    core = sum(c.obj.Volume() for c in assy.children
               if c.name.startswith("fluid_air_core"))
    assert core == pytest.approx(meta["derived"]["V_zone_mm3"], rel=1e-9)


@needs_cad
def test_refrigerant_volume_matches_analytic(p):
    cs = CQC.gen_face_split(p, 4)
    assy, _ = CAD.build(p, cs)
    A = math.pi * p.tube.Di ** 2 / 4
    bends = CQC.derive_bends(p, cs)
    CQC.resolve_standoff(p, bends)
    cad_b = sum(c.obj.Volume() for c in assy.children
                if c.name.startswith("fluid_bend_"))
    assert cad_b == pytest.approx(sum(math.pi * b.R * A for b in bends), rel=1e-9)


@needs_cad
def test_each_circuit_is_one_connected_solid(p):
    """관 끝면과 벤드 끝면이 정확히 맞물려야 유로가 하나로 이어짐"""
    import re
    cs = CQC.gen_face_split(p, 4)
    assy, _ = CAD.build(p, cs)
    RX = re.compile(r"^fluid_ref_r(\d+)t(\d+)$")
    tid = lambda n: (int(RX.match(n).group(1)) - 1) * p.tube.Nt + int(RX.match(n).group(2)) - 1
    for ck in cs.circuits:
        want = set(ck.tubes)
        parts = [c.obj for c in assy.children
                 if c.name.startswith(f"fluid_bend_{ck.id}_")
                 or (RX.match(c.name) and tid(c.name) in want)]
        f = parts[0]
        for q in parts[1:]:
            f = f.fuse(q)
        f = f.clean()
        assert len(f.Solids()) == 1
        assert f.Volume() == pytest.approx(sum(q.Volume() for q in parts), abs=1e-3)


@needs_cad
def test_step_carries_body_names(p, tmp_path):
    cs = CQC.gen_face_split(p, 4)
    meta = CAD.export(p, outdir=str(tmp_path), cs=cs)
    txt = open(meta["_files"]["step"], errors="ignore").read()
    for tag in ("fluid_air_core_r01", "solid_tube_r01t01",
                "fluid_ref_r01t01", "solid_bend_c01_k01"):
        assert f"PRODUCT('{tag}'" in txt


@needs_cad
@needs_cp
def test_plenum_connects_every_circuit(p):
    """입구 플레넘 → 피더 → 회로 가 하나의 솔리드로 이어져야 함"""
    import re
    cs, pl = CQC.gen_face_split(p, 5), DST.PlenumSpec()
    assy, meta = CAD.build(p, cs, pl)
    RX = re.compile(r"^fluid_ref_r(\d+)t(\d+)$")
    tid = lambda n: (int(RX.match(n).group(1)) - 1) * p.tube.Nt + int(RX.match(n).group(2)) - 1
    plen = [c.obj for c in assy.children if c.name.startswith("fluid_plenum_")]
    for ck in cs.circuits:
        want = set(ck.tubes)
        parts = plen + [c.obj for c in assy.children
                        if c.name.startswith(f"fluid_feed_{ck.id}_")
                        or c.name.startswith(f"fluid_bend_{ck.id}_")
                        or (RX.match(c.name) and tid(c.name) in want)]
        f = parts[0]
        for q in parts[1:]:
            f = f.fuse(q)
        assert len(f.clean().Solids()) == 1
    assert len(meta["plenum"]["jumps"]) == len(cs.circuits)


# ─────────────────────────── 핀 팩 분리 (v0.5.0) ───────────────────────────
def test_fin_pack_defaults_are_backward_compatible(p):
    """기본값은 기존 동작(핀이 관 전장을 채움)을 정확히 재현해야 함"""
    b = p.fin_pack
    assert (b["z0"], b["z1"]) == (0.0, p.tube.L)
    assert b["L_fin"] == p.tube.L
    assert p.derived()["N_fin"] == 275
    assert p.derived()["sigma"] == pytest.approx(0.5915539370, abs=1e-9)


def test_fin_pack_scales_extensive_only():
    """핀 팩을 줄이면 크기량만 줄고 세기량(σ, D_h, a_v, γ)은 불변"""
    a = FTHXParams().derived()
    b = FTHXParams(fin={"FPI": 14, "t_f": 0.115, "L_fin": 440}).derived()
    r = 440.0 / 500.0
    for k in ("N_fin", "A_front_mm2", "A_o_mm2", "V_zone_mm3"):
        assert b[k] == pytest.approx(a[k] * r, rel=1e-6)
    for k in ("sigma", "D_h_mm", "a_v_1perm", "porosity_gamma"):
        assert b[k] == pytest.approx(a[k], rel=1e-12)
    assert b["bare_tube_mm"] == pytest.approx(60.0)


def test_fin_height_independent():
    a = FTHXParams(fin={"FPI": 14, "t_f": 0.115, "edge_y": 8.0})
    assert (a.fin_pack["y1"] - a.fin_pack["y0"]) == pytest.approx(308.1, abs=0.05)
    assert a.derived()["sigma"] == pytest.approx(0.581022152, abs=1e-8)


def test_operating_block_and_schema_version(p):
    assert p.schema_version == "fthx/1"
    o = p.operating_derived()
    assert o["air"]["rho"] == pytest.approx(1.1686, abs=1e-3)
    assert 300 < o["air"]["Re_Dc"] < 5000          # Wang 상관식 적용 범위
    assert o["air"]["u_max_ms"] == pytest.approx(
        p.operating.air.V_face / p.derived()["sigma"], rel=1e-12)
    assert o["thermal"] == "equilibrium"


def test_air_props_fallback_without_coolprop(p, monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("CoolProp"):
            raise ImportError
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    pr = p.air_props()
    assert pr["source"] == "dry-air ideal"
    assert 1.0 < pr["rho"] < 1.3


@pytest.mark.parametrize("kw", [{"L_fin": 600}, {"L_fin": 440, "z_center": 100},
                                {"edge_y": 4.0}])
def test_fin_pack_validators(kw):
    with pytest.raises(ValueError):
        FTHXParams(fin=dict({"FPI": 14, "t_f": 0.115}, **kw))


@needs_cad
def test_tubes_extend_beyond_fin_pack():
    """관은 핀 팩 밖까지 나가고, 벤드는 관 끝단에 붙어야 함"""
    p = FTHXParams(fin={"FPI": 14, "t_f": 0.115, "L_fin": 440})
    cs = CQC.gen_face_split(p, 4)
    assy, meta = CAD.build(p, cs)
    B = {c.name: c.obj for c in assy.children}
    tb = B["solid_tube_r01t01"].BoundingBox()
    assert (tb.zmin, tb.zmax) == pytest.approx((0.0, p.tube.L), abs=1e-6)
    cb = B["fluid_air_core_r01"].BoundingBox()
    assert (cb.zmin, cb.zmax) == pytest.approx((30.0, 470.0), abs=1e-6)
    ub = B["fluid_air_up"].BoundingBox()
    assert (ub.zmin, ub.zmax) == pytest.approx((cb.zmin, cb.zmax), abs=1e-6)
    core = sum(v.Volume() for k, v in B.items() if k.startswith("fluid_air_core"))
    assert core == pytest.approx(p.derived()["V_zone_mm3"], rel=1e-9)
    assert all(q["seed"][2] in (0.0, p.tube.L) for q in meta["circuits"]["ports"])


# ─────────────────────────── 덕트 · 바이패스 (v0.5.0) ───────────────────────────
def test_duct_sealed_by_default(p):
    assert p.duct_box["sealed"] is True
    assert p.derived()["bypass_area_frac"] == 0.0


def test_bypass_metrics():
    q = FTHXParams(fin={"FPI": 14, "t_f": 0.115, "L_fin": 440},
                   duct={"gap_y": 6, "gap_z": 8})
    d = q.derived()
    assert d["duct_H_mm"] == pytest.approx(317.5 + 12, abs=1e-9)
    assert d["duct_L_mm"] == pytest.approx(440 + 16, abs=1e-9)
    assert d["bypass_area_frac"] == pytest.approx(0.0702, abs=5e-4)
    assert d["Dh_bypass_y_mm"] > 0 and d["Dh_bypass_z_mm"] > 0


def test_duct_validator():
    with pytest.raises(ValueError):
        FTHXParams(duct={"gap_z": 40})          # 덕트가 관 길이를 벗어남


@needs_cad
def test_bypass_partition_is_exact():
    """코어 + 바이패스 = 덕트 체적 − 관 체적 (겹침·틈 없음)"""
    import math
    q = FTHXParams(fin={"FPI": 14, "t_f": 0.115, "L_fin": 440},
                   duct={"gap_y": 6, "gap_z": 8})
    assy, _ = CAD.build(q, CQC.gen_face_split(q, 4))
    B = {c.name: c.obj for c in assy.children}
    core = sum(v.Volume() for k, v in B.items() if k.startswith("fluid_air_core"))
    byp = sum(v.Volume() for k, v in B.items() if k.startswith("fluid_air_bypass"))
    dk = q.duct_box
    W, Hd, Ld = dk["x1"] - dk["x0"], dk["y1"] - dk["y0"], dk["z1"] - dk["z0"]
    V = W * Hd * Ld - q.tube.Nr * q.tube.Nt * math.pi * q.tube.Do ** 2 / 4 * Ld
    assert core + byp == pytest.approx(V, abs=1e-3)


@needs_cad
def test_bypass_interfaces_are_conformal():
    """상·하류 박스가 핀 팩 경계에서 쪼개져 코어·바이패스와 각각 면을 공유해야 함"""
    q = FTHXParams(fin={"FPI": 14, "t_f": 0.115, "L_fin": 440},
                   duct={"gap_y": 6, "gap_z": 8})
    assy, _ = CAD.build(q, CQC.gen_face_split(q, 4))
    B = {c.name: c.obj for c in assy.children}

    def shared(n1, n2):
        out = []
        for f1 in B[n1].Faces():
            for f2 in B[n2].Faces():
                c1, c2 = f1.Center(), f2.Center()
                if abs(f1.Area() - f2.Area()) < 1e-6 and max(
                        abs(c1.x - c2.x), abs(c1.y - c2.y), abs(c1.z - c2.z)) < 1e-6:
                    out.append(f1.Area())
        return out

    for a, b in [("fluid_air_up_core", "fluid_air_core_r01"),
                 ("fluid_air_up_bypass", "fluid_air_bypass_r01"),
                 ("fluid_air_core_r01", "fluid_air_bypass_r01"),
                 ("fluid_air_core_r04", "fluid_air_down_core")]:
        assert shared(a, b), f"{a} ↔ {b} 공유면 없음"


# ─────────────────────────── 벤드 규격 (v0.5.0) ───────────────────────────
def test_bend_defaults_to_semicircle(p):
    b = CQC.derive_bends(p, CQC.gen_face_split(p, 4))[0]
    assert b.R == pytest.approx(b.span / 2)
    assert b.straight == pytest.approx(0.0)
    assert b.path_len == pytest.approx(math.pi * b.span / 2)


def test_bend_radius_clamped_to_half_span():
    """R/D 를 크게 줘도 평면 U 벤드는 span/2 를 넘을 수 없음"""
    q = FTHXParams(bend={"R_over_D": 1.5, "leg": 6})
    b = CQC.derive_bends(q, CQC.gen_face_split(q, 4))[0]
    assert b.R == pytest.approx(b.span / 2)
    assert b.protrusion == pytest.approx(6 + b.span / 2)


@pytest.mark.parametrize("rd,leg", [(1.0, 6.0), (0.7, 4.0)])
def test_bend_polyline_matches_analytic_path(rd, leg):
    import numpy as np
    q = FTHXParams(bend={"R_over_D": rd, "leg": leg})
    b = CQC.derive_bends(q, CQC.gen_face_split(q, 4))[0]
    assert b.straight == pytest.approx(b.span - 2 * b.R)
    P = CQC.bend_polyline(q, b, n_arc=400)
    L = float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())
    assert L == pytest.approx(b.path_len, rel=1e-4)
    xy = CQC.tube_xy(q)
    z0, z1 = CQC.z_ends(q)
    ze = z1 if b.end == "z1" else z0
    for t, pt in ((b.a, P[0]), (b.b, P[-1])):
        assert np.linalg.norm(pt - np.array([xy[t][0], xy[t][1], ze])) < 1e-9


@needs_cad
@pytest.mark.parametrize("kw", [{}, {"R_over_D": 1.0, "leg": 6.0}])
def test_bend_solid_volume_matches_path(kw):
    q = FTHXParams(bend=kw)
    cs = CQC.gen_face_split(q, 4)
    assy, _ = CAD.build(q, cs)
    bends = CQC.derive_bends(q, cs)
    CQC.resolve_standoff(q, bends)
    A = math.pi * q.tube.Di ** 2 / 4
    cad = sum(c.obj.Volume() for c in assy.children
              if c.name.startswith("fluid_bend_"))
    assert cad == pytest.approx(sum(b.path_len * A for b in bends), rel=1e-9)


# ─────────────────────── 간섭 검사 확장 (v0.5.0) ───────────────────────
@needs_cp
def test_default_layout_has_no_clearance_conflict(p):
    r = DST.check_clearances(p, CQC.gen_face_split(p, 5), DST.PlenumSpec())
    assert r["ok"] and r["offset_ok"]


@needs_cp
def test_plenum_conflict_is_resolvable_by_offset():
    """플레넘↔벤드는 거리를 늘리면 풀림"""
    q = FTHXParams(bend={"R_over_D": 1.0, "leg": 20})
    cs = CQC.gen_face_split(q, 5)
    tight = DST.check_clearances(q, cs, DST.PlenumSpec(offset=25))
    assert tight["plenum_vs_bend"]["n"] > 0 and not tight["offset_ok"]
    ok = DST.check_clearances(q, cs, DST.PlenumSpec(offset=tight["min_offset_mm"] + 2))
    assert ok["ok"]


@needs_cp
def test_feeder_conflict_is_structural():
    """입출구 관이 다른 벤드 아래 깔리면 offset 으로 못 풂 → 회로를 바꿔야 함"""
    q = FTHXParams()
    rest = [t for t in range(q.tube.Nr * q.tube.Nt) if t not in (0, 1, 2, 3)]
    cs = CQC.CircuitSet(circuits=[
        CQC.Circuit(id="cA", tubes=[0, 2], inlet_end="z0"),
        CQC.Circuit(id="cB", tubes=[1, 3], inlet_end="z1"),
        CQC.Circuit(id="cR", tubes=rest, inlet_end="z0")])
    r = DST.check_clearances(q, cs, DST.PlenumSpec())
    assert r["feeder_vs_bend"]["n"] >= 1
    assert any(h["port"] == "ref_inlet_cB" for h in r["feeder_vs_bend"]["hits"])
    far = DST.check_clearances(q, cs, DST.PlenumSpec(offset=200))
    assert far["feeder_vs_bend"]["n"] >= 1        # 거리를 늘려도 그대로


@needs_cad
@needs_cp
def test_auto_offset_resolves_and_is_reported():
    q = FTHXParams(bend={"R_over_D": 1.0, "leg": 20})
    cs = CQC.gen_face_split(q, 5)
    _, m1 = CAD.build(q, cs, DST.PlenumSpec(offset=25))
    assert m1["plenum"]["clearance"]["plenum_vs_bend"]["n"] > 0
    _, m2 = CAD.build(q, cs, DST.PlenumSpec(offset=25, auto_offset=True))
    assert m2["plenum"]["clearance"]["ok"]
    assert m2["plenum"]["offset_mm"] > 25


# ─────────────────── 대칭 · 가드 · STEP 옵션 (v0.5.0) ───────────────────
def test_symmetry_requires_air_side_only():
    for kw in ({"symmetry": "z", "include_bends": True},
               {"symmetry": "z", "include_tube_fluid": True}):
        with pytest.raises(ValueError):
            FTHXParams(domain=kw)
    q = FTHXParams(domain={"symmetry": "z", "include_bends": False,
                           "include_tube_fluid": False})
    assert q.sym_z == pytest.approx(q.tube.L / 2)


@needs_cad
def test_symmetry_halves_the_model():
    kw = dict(fin={"FPI": 14, "t_f": 0.115, "L_fin": 440},
              duct={"gap_y": 6, "gap_z": 8})
    dom = {"include_bends": False, "include_tube_fluid": False}
    full, _ = CAD.build(FTHXParams(domain=dom, **kw))
    half, m = CAD.build(FTHXParams(domain=dict(dom, symmetry="z"), **kw))
    Vf = sum(c.obj.Volume() for c in full.children)
    Vh = sum(c.obj.Volume() for c in half.children)
    assert Vh == pytest.approx(Vf / 2, rel=1e-9)
    assert m["symmetry"]["plane"] == "z"
    assert "symmetry_z" in m["face_seeds"]
    for c in half.children:
        assert c.obj.BoundingBox().zmin >= m["symmetry"]["z"] - 1e-6


@needs_cad
def test_plenum_guard_without_circuits(p):
    """벤드가 없으면 관마다 독립 회로가 되어 피더가 폭발함 → 막아야 함"""
    with pytest.raises(ValueError, match="독립 회로"):
        CAD.build(p, None, DST.PlenumSpec())


@needs_cad
@pytest.mark.parametrize("ex", [{}, {"precision_mode": 1}, {"write_pcurves": False}])
def test_step_export_options(ex, tmp_path):
    import re
    q = FTHXParams(name="opt", export=ex)
    m = CAD.export(q, outdir=str(tmp_path), cs=CQC.gen_face_split(q, 4))
    txt = open(m["_files"]["step"], errors="ignore").read()
    assert len(re.findall(r"PRODUCT\('([^']+)'", txt)) == 191


# ─────────────────── 입구 발달 스터브 (v0.6.0) ───────────────────
@needs_cp
def test_entry_length_regimes():
    lam = DST.entry_length(8.22, 1e-5, 38.18, 12.46e-6)
    tur = DST.entry_length(8.22, 7.5e-3, 38.18, 12.46e-6)
    assert lam["regime"] == "laminar" and tur["regime"] == "turbulent"
    assert tur["Le_over_D"] == pytest.approx(4.4 * tur["Re"] ** (1 / 6), rel=1e-12)


@needs_cp
def test_stub_development_criteria(p):
    pl = DST.PlenumSpec(stub_len=0)
    d = DST.stub_development(p, pl, DST.Fluid(), 0.030)
    assert d["Le_practical_mm"] == pytest.approx(10 * pl.stub_dia())
    assert d["Le_full_mm"] > d["Le_practical_mm"]          # Re 가 크면 full > 10D
    assert not d["developed_practical"] and not d["developed_full"]
    ok = DST.stub_development(p, DST.PlenumSpec(stub_len=d["Le_full_mm"] + 1),
                              DST.Fluid(), 0.030)
    assert ok["developed_full"] and ok["developed_practical"]


@needs_cad
@needs_cp
def test_stub_geometry_and_port_moves(p):
    cs = CQC.gen_face_split(p, 4)
    _, m0 = CAD.build(p, cs, DST.PlenumSpec())
    _, m1 = CAD.build(p, cs, DST.PlenumSpec(stub_len=160))
    y0 = [q for q in m0["plenum"]["plenums"] if q["kind"] == "inlet"][0]["main_port_seed"][1]
    y1 = [q for q in m1["plenum"]["plenums"] if q["kind"] == "inlet"][0]["main_port_seed"][1]
    assert y1 == pytest.approx(y0 - 160)                   # 입구면이 스터브 끝으로 이동
    assy, _ = CAD.build(p, cs, DST.PlenumSpec(stub_len=160))
    B = {c.name: c.obj for c in assy.children}
    # 출구 끝단은 회로 관 수의 홀짝에 따라 달라지므로 이름을 고정하지 않음
    stubs = sorted(k for k in B if k.startswith("fluid_stub_"))
    assert any(k.startswith("fluid_stub_in_") for k in stubs)
    assert any(k.startswith("fluid_stub_out_") for k in stubs)
    # 스터브 ↔ 플레넘 conformal
    sin = next(k for k in stubs if k.startswith("fluid_stub_in_"))
    hits = []
    for f1 in B[sin].Faces():
        for f2 in B[sin.replace("stub", "plenum")].Faces():
            c1, c2 = f1.Center(), f2.Center()
            if abs(f1.Area() - f2.Area()) < 1e-6 and max(
                    abs(c1.x - c2.x), abs(c1.y - c2.y), abs(c1.z - c2.z)) < 1e-6:
                hits.append(f1.Area())
    assert hits, "스터브와 플레넘이 면을 공유하지 않음"


@needs_cad
@needs_cp
@pytest.mark.parametrize("crit,flag", [("practical", "developed_practical"),
                                       ("full", "developed_full")])
def test_stub_auto_satisfies_criterion(p, crit, flag):
    _, m = CAD.build(p, CQC.gen_face_split(p, 4),
                     DST.PlenumSpec(stub_auto=True, stub_criterion=crit))
    assert m["plenum"]["stub_development"][flag] is True


# ─────────────────── 냉매 입출구 관 연장 (v0.6.0) ───────────────────
@needs_cad
def test_port_stub_extends_only_port_tubes():
    q = FTHXParams(domain={"include_bends": True, "include_tube_fluid": True,
                           "port_stub": 250})
    cs = CQC.gen_face_split(q, 4)
    assy, m = CAD.build(q, cs)
    B = {c.name: c.obj for c in assy.children}
    assert m["port_stub"]["len_mm"] == pytest.approx(250)
    # 회로당 관 12개(짝수) → 입·출구가 같은 끝단(z0)
    assert sorted({round(p["seed"][2], 1) for p in m["circuits"]["ports"]}) == [-250.0]
    t0 = cs.circuits[0].tubes[0]
    r0, i0 = divmod(t0, q.tube.Nt)
    bb = B[f"solid_tube_r{r0+1:02d}t{i0+1:02d}"].BoundingBox()
    assert bb.zmin == pytest.approx(-250, abs=1e-6)
    # 회로 중간 관은 연장되지 않아야 함
    tm = cs.circuits[0].tubes[len(cs.circuits[0].tubes) // 2]
    rm, im = divmod(tm, q.tube.Nt)
    bm = B[f"solid_tube_r{rm+1:02d}t{im+1:02d}"].BoundingBox()
    assert bm.zmin >= -1e-6 and bm.zmax <= q.tube.L + 1e-6


@needs_cad
@needs_cp
@pytest.mark.parametrize("crit,mult", [("practical", 10.0), ("full", None)])
def test_port_stub_auto(crit, mult):
    q = FTHXParams(domain={"include_bends": True, "include_tube_fluid": True,
                           "port_stub_auto": True, "port_stub_criterion": crit})
    _, m = CAD.build(q, CQC.gen_face_split(q, 4))
    e = m["port_stub"]
    need = mult * q.tube.Di if mult else e["Le_mm"]
    assert e["len_mm"] >= need - 1e-9
    assert sorted({round(p["seed"][2], 1) for p in m["circuits"]["ports"]}) == [-e["len_mm"]]


# ─────────────────── 방향 반전 (v0.6.0) ───────────────────
@pytest.mark.parametrize("n,exp", [(1, "z1"), (2, "z0"), (3, "z1"), (12, "z0")])
def test_outlet_end_rule(n, exp):
    """관 하나를 지날 때마다 끝단이 뒤집힘. 단일 관은 반드시 반대편."""
    assert CQC.outlet_end("z0", n) == exp


def test_single_tube_ports_are_on_opposite_ends(p):
    cs = CQC.CircuitSet(circuits=[CQC.Circuit(id="c01", tubes=[0], inlet_end="z0")])
    ends = {q["kind"]: q["end"] for q in CQC.io_ports(p, cs)}
    assert ends["inlet"] != ends["outlet"]


@pytest.mark.parametrize("gen", ["single", "row_serpentine", "face_split"])
def test_reverse_preserves_bend_geometry_and_swaps_ports(p, gen):
    cs = (CQC.gen_face_split(p, 4) if gen == "face_split"
          else CQC.GENERATORS[gen](p))
    rv = CQC.reverse_all(cs)
    key = lambda b: (min(b.a, b.b), max(b.a, b.b), b.end, round(b.R, 9),
                     round(b.straight, 9))
    assert {key(b) for b in CQC.derive_bends(p, cs)} == \
           {key(b) for b in CQC.derive_bends(p, rv)}
    f = lambda ps, k: sorted((q["tube"], q["end"]) for q in ps if q["kind"] == k)
    a, b = CQC.io_ports(p, cs), CQC.io_ports(p, rv)
    assert f(a, "inlet") == f(b, "outlet") and f(a, "outlet") == f(b, "inlet")
    assert CQC.build(p, rv)["ok"]


def test_reverse_is_involutive(p):
    cs = CQC.gen_face_split(p, 4)
    back = CQC.reverse_all(CQC.reverse_all(cs))
    assert [c.tubes for c in back.circuits] == [c.tubes for c in cs.circuits]
    assert [c.inlet_end for c in back.circuits] == [c.inlet_end for c in cs.circuits]


def test_reverse_subset_only(p):
    cs = CQC.gen_face_split(p, 4)
    rv = CQC.apply_reverse(cs, ["c02"])
    assert rv.circuits[0].tubes == cs.circuits[0].tubes
    assert rv.circuits[1].tubes == list(reversed(cs.circuits[1].tubes))


# ─────────────────── 프리셋 (튜토리얼 / 시험) ───────────────────
def test_presets_are_valid():
    from fthx import presets
    for name, fn in presets.PRESETS.items():
        p = fn()
        assert p.schema_version == "fthx/1"
        d = p.derived()
        assert d["N_fin"] > 0 and 0 < d["porosity_gamma"] < 1


@needs_cad
def test_tutorial_has_five_bodies_and_opposite_ports():
    from fthx import presets
    p = presets.tutorial()
    assy, m = CAD.build(p)
    names = sorted(c.name for c in assy.children)
    assert names == ["fluid_air_core_r01", "fluid_air_down", "fluid_air_up",
                     "fluid_ref_r01t01", "solid_tube_r01t01"]
    ends = {q["kind"]: q["end"] for q in m["circuits"]["ports"]}
    assert ends["inlet"] != ends["outlet"]        # 관 1개 → 반대편
    # 튜토리얼은 L_fin=L 이라 관 외벽면과 코어 구멍면이 정확히 일치해야 함
    # (imprint 없이 Share Topology 로 바로 붙는 가장 쉬운 조건)
    assert p.fin_pack["z0"] == 0 and p.fin_pack["z1"] == p.tube.L
    B = {c.name: c.obj for c in assy.children}

    def exact(n1, n2):
        return [f1.Area() for f1 in B[n1].Faces() for f2 in B[n2].Faces()
                if abs(f1.Area() - f2.Area()) < 1e-6
                and (f1.Center() - f2.Center()).Length < 1e-6]

    assert exact("solid_tube_r01t01", "fluid_air_core_r01"), "포러스↔관벽 공유면 없음"
    assert exact("solid_tube_r01t01", "fluid_ref_r01t01"), "관벽↔냉매 공유면 없음"


@needs_cad
def test_probe_is_harder_than_tutorial():
    """probe 는 일부러 어려운 조건 — 핀팩이 관보다 짧아 imprint 가 필요함"""
    from fthx import presets
    p = presets.probe()
    assy, _ = CAD.build(p, CQC.gen_single(p))
    assert len(assy.children) == 13
    assert p.fin_pack["z0"] > 0 and p.fin_pack["z1"] < p.tube.L


# ─────────────────── 메시 사이징 유도 ───────────────────
def test_sizing_is_derived_from_geometry(p):
    from fthx import meshing
    s = meshing.sizing(p)
    assert s["h_air_mm"] == pytest.approx((p.tube.Pt - p.tube.Do) / 10)
    assert s["h_wall_mm"] == pytest.approx((p.tube.Do - p.tube.Di) / 2 / 1)
    assert s["h_ref_mm"] == pytest.approx(p.tube.Di / 12)
    # 관 표면은 코어·냉매와 공유되므로 관벽 두께가 표면 크기를 지배하면 안 됨
    assert s["workflow_min_mm"] == pytest.approx(round(s["h_ref_mm"], 3))
    assert s["workflow_min_mm"] < s["workflow_max_mm"]
    # 고전도 박벽은 두께 방향 등온 → thin volume 전략
    assert s["wall"]["Biot"] < 0.01
    assert s["wall"]["strategy"] == "thin_volume"


def test_sizing_scales_with_geometry():
    from fthx import meshing
    thin = FTHXParams(tube={"Do": 9.52, "Di": 9.0})     # 관벽 0.26mm
    assert meshing.sizing(thin)["h_wall_mm"] < \
           meshing.sizing(FTHXParams())["h_wall_mm"]


# ─────────────────── C: 메시 전략 · 셀 추정 ───────────────────
@pytest.mark.parametrize("name,actual", [("tutorial", 68641), ("probe", 164461)])
def test_estimator_brackets_measured_cells(name, actual):
    """Fluent 2025R1 실측값이 추정 범위 안에 들어와야 함"""
    from fthx import presets, meshing
    p = presets.PRESETS[name]()
    cs = CQC.gen_single(p) if p.domain.include_bends else None
    e = meshing.estimate(p, cs)
    assert e["low"] <= actual <= e["high"]
    assert abs(e["total"] / actual - 1) < 0.15          # 중앙값 ±15% 이내


def test_wall_treatment_no_prism_needed(p):
    """현재 사이징이 벽함수 범위(30<y+<300) 안이면 프리즘 불필요"""
    from fthx import meshing
    w = meshing.wall_treatment(p, n_circuit=4)
    assert 30 <= w["y_plus"] <= 300
    assert w["prism_needed"] is False


def test_wall_treatment_flags_buffer_layer(p):
    """유량이 크게 낮아지면 완충층에 들어가 경고해야 함"""
    from fthx import meshing
    w = meshing.wall_treatment(p, n_circuit=4, m_total=0.0015)
    assert w["y_plus"] < 30
    assert w["prism_needed"] is True


def test_feasibility_flags_extension_dominance():
    from fthx import meshing
    q = FTHXParams(domain={"L_up": 132, "L_down": 440,
                           "include_bends": True, "include_tube_fluid": True})
    f = meshing.feasibility(q, CQC.gen_face_split(q, 4), budget=20e6)
    assert any("상·하류" in i for i in f["issues"])
    assert f["hint"]["save_by_halving_L_down"] > 0


def test_estimate_zone_breakdown_sums(p):
    from fthx import meshing
    e = meshing.estimate(p, CQC.gen_face_split(p, 4))
    assert sum(r["cells"] for r in e["zones"]) == pytest.approx(e["total"])
    assert sum(r["frac"] for r in e["zones"]) == pytest.approx(1.0)
    assert e["zones"][0]["cells"] >= e["zones"][-1]["cells"]    # 내림차순


# ─────────────────── M1: 메시 생성기 (Fluent 없이 되는 부분) ───────────────────
def test_step_body_count_matches_cad():
    from fluent.mesh import step_bodies
    from fthx import presets
    import tempfile
    p = presets.probe()
    if not HAS_CAD:
        pytest.skip("cadquery 필요")
    with tempfile.TemporaryDirectory() as d:
        m = CAD.export(p, outdir=d, cs=CQC.gen_single(p))
        assert len(step_bodies(Path(m["_files"]["step"]))) == 13


@pytest.mark.parametrize("st,expect_issue", [
    ({"cell_zones": 13, "expected_zones": 13, "cells": 164461, "min_quality": 0.225}, None),
    ({"cell_zones": 11, "expected_zones": 13, "cells": 164461, "min_quality": 0.225}, "셀 존"),
    ({"cell_zones": 13, "expected_zones": 13, "cells": 164461, "min_quality": 0.05}, "직교품질"),
    ({"cell_zones": 13, "expected_zones": 13, "cells": 25_000_000, "min_quality": 0.3}, "예산"),
])
def test_quality_gate(st, expect_issue):
    from fluent.mesh import MeshRun, gate
    from fthx import presets
    run = MeshRun(step=Path("x.step"), params=presets.probe(), budget=20e6)
    issues = gate(run, st)
    if expect_issue is None:
        assert issues == []
    else:
        assert any(expect_issue in i for i in issues)


def test_retry_ladder_monotonically_refines():
    """사다리를 올라갈수록 셀이 늘어야 함 (더 촘촘해지므로)"""
    from fluent.mesh import LADDER
    from fthx import presets, meshing
    p = presets.probe()
    prev = 0.0
    for label, over in LADDER:
        ms = meshing.MeshSpec(**over)
        n = meshing.estimate(p, None, ms)["total"]
        assert n >= prev, f"{label} 에서 셀이 줄어듦"
        prev = n


# ─────────────────── 해석 패키지 내보내기 ───────────────────
def test_fluent_journal_is_valid_python():
    import ast
    from fthx import presets, exporters
    for name in ("tutorial", "probe"):
        j = exporters.fluent_journal(presets.PRESETS[name](), n_bodies=13)
        ast.parse(j)                                  # 문법 오류 없어야 함
        assert "CELLS_PER_GAP = 1" in j               # M0 실측 반영
        assert "Watertight Geometry" in j
        assert "InvokeShareTopology" in j


def test_journal_embeds_derived_sizing():
    from fthx import presets, exporters, meshing
    p = presets.probe()
    s = meshing.sizing(p)
    j = exporters.fluent_journal(p)
    assert f"MIN_SIZE    = {s['workflow_min_mm']}" in j
    assert f"MAX_SIZE    = {s['workflow_max_mm']}" in j


def test_run_md_and_settings_have_key_values():
    from fthx import presets, exporters, meshing
    p = presets.probe()
    s = meshing.sizing(p)
    md = exporters.run_md(p, est=meshing.estimate(p), n_bodies=13)
    st = exporters.settings_txt(p, n_bodies=13)
    for txt in (md, st):
        assert str(s["workflow_min_mm"]) in txt
        assert str(s["surface"]["cells_per_gap"]) in txt
    assert "fluent 3d -meshing -g -t8 -i mesh.py" in md
    assert "13" in md                                 # 기대 셀 존 수


def test_journal_has_tui_fallbacks():
    """2025R1 실측: 'tui' 가 전역에 없어 8~10단계가 실패했음"""
    from fthx import presets, exporters
    j = exporters.fluent_journal(presets.probe())
    assert "def TUI():" in j
    assert "TUI 진입점을 찾지 못함" in j
    assert "_write_any" in j                    # 저장은 대안 경로까지
    assert "11. 전역 이름 덤프" in j            # 실패 시 진단


def test_run_md_warns_core_count_affects_cells():
    from fthx import presets, exporters, meshing
    p = presets.probe()
    md = exporters.run_md(p, est=meshing.estimate(p), n_bodies=13)
    assert "코어 수가 셀 수에 영향" in md
    assert "229,026" in md


def test_journal_embeds_face_seeds():
    """M2 준비 — 좌표 라벨링 탐색 단계에 seed 가 실려야 함"""
    from fthx import presets, exporters
    seeds = {"air_inlet": [-40.0, 12.7, 50.0], "ref_inlet_c01": [11.0, 12.7, 0.0]}
    j = exporters.fluent_journal(presets.probe(), face_seeds=seeds)
    assert "FACE_SEEDS = {" in j
    assert "air_inlet" in j and "ref_inlet_c01" in j
    assert "meshing_utilities" in j
    assert "12. 면 존 표" in j


def test_journal_m2_labeling_section():
    """M2 — 확정된 시그니처가 저널에 들어가야 함 (2025R1 실측)"""
    from fthx import presets, exporters
    j = exporters.fluent_journal(presets.probe(),
                                 face_seeds={"air_inlet": [-40.0, 38.1, 50.0]})
    assert 'MU.get_face_zones(filter="*")' in j
    assert "get_average_bounding_box_center(face_zone_id_list=[zid])" in j
    assert "get_face_zone_area(face_zone_id_list=[zid])" in j
    assert "sep_face_zone_by_angle" in j
    assert "13a. TUI 트리에서 분리 명령 찾기" in j          # 바디 단위 존을 면 단위로
    assert "14. face_seeds 좌표 매칭" in j
    assert "_labeled.msh" in j                     # 라벨된 메시 별도 저장
