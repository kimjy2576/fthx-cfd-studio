"""
검증 스위트 — 개발 중 수행한 확인들을 그대로 회귀 테스트로 고정.

    pytest -q                    (cadquery 없으면 형상 테스트는 자동 skip)
"""
import math

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
    """Wang 정의 파생량 기준값 (GUI 의 JS 구현과 일치해야 하는 값)"""
    d = p.derived()
    assert d["porosity_gamma"] == pytest.approx(0.93675, abs=1e-6)
    assert d["sigma"] == pytest.approx(0.5996970236, abs=1e-9)
    assert d["a_v_1perm"] == pytest.approx(1154.836862, abs=1e-5)
    assert d["D_h_mm"] == pytest.approx(2.366565245, abs=1e-8)
    assert d["N_fin"] == 275


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
