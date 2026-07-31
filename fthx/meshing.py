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
    N_wall: int = Field(3, ge=1, description="관벽 두께 분할 수")
    N_d: int = Field(12, ge=4, description="관 내경 분할 수")
    N_arc: int = Field(24, ge=8, description="벤드 반원 분할 수")
    growth: float = Field(1.2, gt=1, description="성장률")


def sizing(p: FTHXParams, ms: Optional[MeshSpec] = None) -> dict:
    """바디 클래스별 셀 크기 [mm]와 워크플로우에 넣을 min/max."""
    ms = ms or MeshSpec()
    t = p.tube
    h_air = (t.Pt - t.Do) / ms.N_gap
    h_wall = (t.Do - t.Di) / 2.0 / ms.N_wall
    h_ref = t.Di / ms.N_d
    R_min = t.Pt / 2.0
    h_bend = min(h_ref, math.pi * R_min / ms.N_arc)
    per_body = {
        "fluid_air_up/down": h_air * 2.0,      # 연장부는 굵게
        "fluid_air_core_*": h_air,
        "solid_tube_*": h_wall,
        "fluid_ref_*": h_ref,
        "*_bend_*": h_bend,
    }
    h_min = min(per_body.values())
    h_max = max(per_body.values())

    # Fluent 의 Min size 는 하한선이지 목표가 아님. 곡률·근접 조건이 요구할 때만
    # 그 크기로 내려감. 관벽처럼 얇지만 곡률이 완만한 바디는 자동으로 안 잡히므로
    # Local Sizing 을 직접 걸어야 함. (2025R1 실측: 관벽 0.65mm 에 셀 1겹만 들어감)
    local = [
        {"name": "tube-wall", "scope": "solid_tube_*", "type": "face-and-body",
         "size_mm": round(h_wall, 3),
         "why": f"관벽 {(t.Do-t.Di)/2:.2f}mm 를 {ms.N_wall}겹으로 — "
                "conjugate 열전도 성립 조건"},
        {"name": "tube-inner", "scope": "fluid_ref_*", "type": "face-and-body",
         "size_mm": round(h_ref, 3), "why": "관내 유동"},
    ]
    if p.domain.include_bends:
        local.append({"name": "bend", "scope": "*_bend_*", "type": "face-and-body",
                      "size_mm": round(h_bend, 3), "why": "비정형 벤드 곡률"})

    return {
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
