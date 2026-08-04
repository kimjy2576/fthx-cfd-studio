"""
주기 단위셀 — 핀을 **실형상**으로 푸는 최소 도메인.

포러스를 쓰지 않음. 여기서 h·f 를 직접 추출해 풀사이즈 포러스 케이스에 공급함.
(계획서의 D 모드: periodic_cell → j/f 추출 → B 모드 풀사이즈 포러스)

도메인 (staggered 기준)
-----------------------
    x  유동 방향 : 상류 연장 + Nr 열 + 하류 연장
    y  폭 방향   : 0 ~ Pt/2
                   y=0      관 중심       → 대칭면
                   y=Pt/2   엇갈린 열 관 중심 → 대칭면
    z  핀 방향   : 0 ~ Fp/2
                   z=0      핀 두께 중앙  → 대칭면
                   z=Fp/2   핀 사이 중앙  → 대칭면

네 면이 모두 대칭면이므로 주기 경계가 필요 없음. 셀은 1/4 로 줄어듦.

바디
----
    fluid_cell_up / core / down   공기
    solid_fin                     핀 (z=0 ~ t_f/2, 대칭 반쪽)
    solid_tube_rNN                관벽
    fluid_ref_rNN                 관내 냉매 (선택)

inline 배열이면 y=Pt/2 가 관 사이 중앙이 되어 그대로 성립함.
"""
from __future__ import annotations

import math
from typing import Optional

from .params import FTHXParams


def cell_geometry(p: FTHXParams, n_up: float = 2.0, n_down: float = 4.0) -> dict:
    """단일셀 도메인 치수. n_up/n_down 은 Pl 배수."""
    t, f = p.tube, p.fin
    Fp = f.Fp
    L_up = n_up * t.Pl
    L_dn = n_down * t.Pl
    x_core0 = L_up
    x_core1 = L_up + t.Nr * t.Pl
    return {
        "Lx": L_up + t.Nr * t.Pl + L_dn,
        "Ly": t.Pt / 2.0,
        "Lz": Fp / 2.0,
        "L_up": L_up, "L_down": L_dn,
        "x_core": (x_core0, x_core1),
        "Fp": Fp, "t_f_half": f.t_f / 2.0,
        "gap_half": (Fp - f.t_f) / 2.0,
        "layout": t.layout,
    }


def tube_centers(p: FTHXParams, g: dict) -> list:
    """단일셀 안의 관 중심. staggered 는 열마다 y 가 0 / Pt/2 로 교대."""
    t = p.tube
    x0 = g["x_core"][0]
    out = []
    for r in range(t.Nr):
        x = x0 + (r + 0.5) * t.Pl
        if t.layout == "staggered" and r % 2 == 1:
            y = t.Pt / 2.0          # 대칭면 위 — 반쪽 관이 됨
        else:
            y = 0.0                 # 대칭면 위 — 반쪽 관이 됨
        out.append((r, x, y))
    return out


def build(p: FTHXParams, n_up: float = 2.0, n_down: float = 4.0,
          include_ref: bool = False):
    """CadQuery 어셈블리. 바디 이름은 풀사이즈와 같은 규약을 따름."""
    import cadquery as cq

    g = cell_geometry(p, n_up, n_down)
    t, f = p.tube, p.fin
    Lx, Ly, Lz = g["Lx"], g["Ly"], g["Lz"]
    xc0, xc1 = g["x_core"]
    tf2 = g["t_f_half"]
    Dc = t.Do + 2.0 * f.t_f          # 핀 칼라 외경

    def box(x0, x1, y0, y1, z0, z1):
        return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0,
                                cq.Vector(x0, y0, z0))

    def cyl(r, x, y, z0, z1):
        return cq.Solid.makeCylinder(r, z1 - z0, cq.Vector(x, y, z0),
                                     cq.Vector(0, 0, 1))

    assy = cq.Assembly()
    centers = tube_centers(p, g)

    # 관·칼라를 한 번에 빼내기 위한 컴파운드
    def cut_tubes(body, radius, z0, z1):
        for _r, x, y in centers:
            body = body.cut(cyl(radius, x, y, z0, z1))
        return body

    # ---- 공기 (핀 사이 간극: z = tf2 ~ Lz) ----
    for tag, a, b in (("up", 0.0, xc0), ("core", xc0, xc1),
                      ("down", xc1, Lx)):
        air = box(a, b, 0.0, Ly, tf2, Lz)
        if tag == "core":
            air = cut_tubes(air, Dc / 2.0, tf2 - 1.0, Lz + 1.0)
        else:
            air = cut_tubes(air, t.Do / 2.0, tf2 - 1.0, Lz + 1.0)
        if air.Solids():
            assy.add(air, name=f"fluid_cell_{tag}",
                     color=cq.Color(0.55, 0.75, 0.95))

    # ---- 핀 (z = 0 ~ tf2, 두께 대칭 반쪽) ----
    fin = box(xc0, xc1, 0.0, Ly, 0.0, tf2)
    fin = cut_tubes(fin, Dc / 2.0, -1.0, tf2 + 1.0)
    if fin.Solids():
        assy.add(fin, name="solid_fin", color=cq.Color(0.85, 0.85, 0.88))

    # ---- 관벽 + 칼라 ----
    for r, x, y in centers:
        wall = cyl(t.Do / 2.0, x, y, 0.0, Lz).cut(cyl(t.Di / 2.0, x, y, -1.0, Lz + 1.0))
        collar = cyl(Dc / 2.0, x, y, 0.0, tf2).cut(
            cyl(t.Do / 2.0, x, y, -1.0, tf2 + 1.0))
        body = wall.fuse(collar).clean()
        body = body.intersect(box(0.0, Lx, 0.0, Ly, 0.0, Lz))
        if body.Solids():
            assy.add(body, name=f"solid_tube_r{r+1:02d}",
                     color=cq.Color(0.8, 0.5, 0.2))
        if include_ref:
            ref = cyl(t.Di / 2.0, x, y, 0.0, Lz).intersect(
                box(0.0, Lx, 0.0, Ly, 0.0, Lz))
            if ref.Solids():
                assy.add(ref, name=f"fluid_ref_r{r+1:02d}",
                         color=cq.Color(0.2, 0.4, 0.9))

    # ---- face_seeds ----
    ym, zm = Ly / 2.0, (tf2 + Lz) / 2.0
    seeds = {
        "cell_inlet":  [0.0, ym, zm],
        "cell_outlet": [Lx, ym, zm],
        "sym_y0":      [(xc0 + xc1) / 2.0, 0.0, zm],
        "sym_y1":      [(xc0 + xc1) / 2.0, Ly, zm],
        "sym_z1":      [(xc0 + xc1) / 2.0, ym, Lz],
    }
    meta = {
        "schema_version": p.schema_version,
        "name": f"{p.name}_cell",
        "units": "mm",
        "mode": "periodic_cell",
        "geometry": g,
        "tube_centers": [{"r": r, "x": x, "y": y} for r, x, y in centers],
        "face_seeds": seeds,
        "operating": p.operating.model_dump(),
        "operating_derived": p.operating_derived(),
        "note": "핀 실형상 · 포러스 없음. 네 측면이 모두 대칭면.",
    }
    return assy, meta


def export(p: FTHXParams, outdir: str = "out", **kw) -> dict:
    import json
    import os

    import cadquery as cq

    from . import cad as CAD

    assy, meta = build(p, **kw)
    ov = CAD.check_overlap(assy)
    meta["overlap"] = ov
    if ov:
        raise ValueError("바디 겹침: " + ", ".join(
            f"{o['a']}∩{o['b']}={o['volume_mm3']:.2f}" for o in ov[:5]))

    os.makedirs(outdir, exist_ok=True)
    step = os.path.join(outdir, f"{meta['name']}.step")
    ex = p.export
    assy.export(step, exportType="STEP", unit=ex.unit,
                write_pcurves=ex.write_pcurves,
                precision_mode=ex.precision_mode)
    js = os.path.join(outdir, f"{meta['name']}.json")
    with open(js, "w", encoding="utf-8") as fp:
        json.dump(meta, fp, indent=2, ensure_ascii=False)
    meta["_files"] = {"step": step, "json": js}
    return meta


# ══════════════════════════════════════════════════════════════════
#  메시 사이징 · 운전 조건
# ══════════════════════════════════════════════════════════════════
def cell_sizing(p: FTHXParams, h_xy: float = 0.25,
                nz_gap: int = 10, nz_fin: int = 2) -> dict:
    """단일셀 메시. z 가 0.9mm 로 얇아 이방성이 필요함.

    y+ 는 1 근처이고 Re_Dh ~ 500 (층류) 이므로 벽함수를 쓰지 않음.
    """
    g = cell_geometry(p)
    hz_gap = g["gap_half"] / nz_gap
    hz_fin = g["t_f_half"] / nz_fin
    n_air = (g["Lx"] / h_xy) * (g["Ly"] / h_xy) * nz_gap
    n_fin = ((g["x_core"][1] - g["x_core"][0]) / h_xy) * (g["Ly"] / h_xy) * nz_fin
    return {
        "h_xy_mm": h_xy, "nz_gap": nz_gap, "nz_fin": nz_fin,
        "hz_gap_mm": hz_gap, "hz_fin_mm": hz_fin,
        "aspect_ratio": h_xy / hz_gap,
        "cells_est": n_air + n_fin,
        "note": "z 방향 스윕. 등방 tet 이면 셀이 수십 배로 늘어남",
    }


def cell_flow(p: FTHXParams) -> dict:
    """단일셀 유동 조건. 풀사이즈와 같은 최대유속(G_max)을 재현해야
       추출한 j·f 가 그대로 적용됨."""
    o = p.operating_derived()["air"]
    d = p.derived()
    Dh = d["D_h_mm"] / 1000.0
    Re = o["Re_Dh"]
    return {
        "V_face_ms": p.operating.air.V_face,
        "u_max_ms": o["u_max_ms"],
        "G_max": o["G_max"],
        "Re_Dh": Re, "Re_Dc": o["Re_Dc"],
        "D_h_m": Dh,
        "regime": "laminar" if Re < 2300 else "turbulent",
        "T_in_K": p.operating.air.T_in + 273.15,
        "T_wall_K": p.operating.ref.T_sat_in + 273.15,
        "rho": o["rho"], "mu": o["mu"], "cp": o["cp"],
        "note": ("Re_Dh < 2300 이면 층류로 풀 것. 난류 모델을 켜면 "
                 "가짜 난류점성으로 h 가 과대평가됨"),
    }


def extract_jf(p: FTHXParams, dp_Pa: float, q_W: float,
               t_out_K: float, area_m2: Optional[float] = None) -> dict:
    """단일셀 CFD 결과 → j, f.

    dp_Pa   코어 압력강하 (입구면 - 출구면)
    q_W     셀이 흡수한 열량 (벽면 열유속 적분 또는 공기 엔탈피 변화)
    t_out_K 공기 출구 온도
    """
    fl = cell_flow(p)
    d = p.derived()
    g = cell_geometry(p)
    rho, cp, mu = fl["rho"], fl["cp"], fl["mu"]
    G = fl["G_max"]
    T_in, T_w = fl["T_in_K"], fl["T_wall_K"]

    # f — Kays&London 정의 (최소유동면적 기준)
    A_o_A_c = d["A_o_over_A_c"]
    f = dp_Pa * 2.0 * rho / (G ** 2 * A_o_A_c) if A_o_A_c else None

    # j — 대수평균온도차로 h 산출 후 Colburn
    dT1, dT2 = T_in - T_w, t_out_K - T_w
    lmtd = ((dT1 - dT2) / math.log(dT1 / dT2)
            if dT1 > 0 and dT2 > 0 and abs(dT1 - dT2) > 1e-9 else None)
    A = area_m2
    h = q_W / (A * lmtd) if (A and lmtd) else None
    Pr = cp * mu / 0.0263
    j = h / (G * cp) * Pr ** (2.0 / 3.0) if h else None

    return {"dp_Pa": dp_Pa, "q_W": q_W, "T_out_K": t_out_K,
            "LMTD_K": lmtd, "A_m2": A, "h_W_m2K": h,
            "j": j, "f": f, "Re_Dc": fl["Re_Dc"], "Pr": Pr,
            "note": "이 j·f 를 closure 에 주입하면 상관식 대신 실측값이 됨"}


def heat_area_m2(p: FTHXParams) -> float:
    """셀의 공기측 전열면적 [m2] — 핀 노출면(위) + 관 외벽 노출면."""
    import cadquery as cq  # noqa: F401
    g = cell_geometry(p)
    assy, _ = build(p)
    B = {c.name: c.obj for c in assy.children}
    tf2 = g["t_f_half"]
    A = 0.0
    fin = B.get("solid_fin")
    if fin is not None:
        A += sum(f.Area() for f in fin.Faces()
                 if abs(f.normalAt(f.Center()).z) > 0.99
                 and abs(f.Center().z - tf2) < 1e-9)
    for k, v in B.items():
        if not k.startswith("solid_tube"):
            continue
        for f in v.Faces():
            if f.geomType() != "CYLINDER" or f.Center().z <= tf2 + 1e-9:
                continue
            bb = f.BoundingBox()
            if abs(max(bb.xlen, bb.ylen) / 2 - p.tube.Do / 2) < 1e-3:
                A += f.Area()
    return A / 1e6
