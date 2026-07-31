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

    return {
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
