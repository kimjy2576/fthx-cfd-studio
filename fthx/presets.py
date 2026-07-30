"""미리 정의된 케이스.

tutorial : 관 1개. Fluent 메싱을 처음 시험할 때 쓰는 최소 케이스.
probe    : 관 3개 + 벤드 2개. 튜토리얼 통과 후 벤드 메싱을 확인할 때.
"""
from __future__ import annotations

from .params import FTHXParams, TubeSpec, FinSpec, DomainSpec


def tutorial() -> FTHXParams:
    """관 1개 · 벤드 없음 — 5 바디.

    구조적으로 확인해야 할 것은 다 들어 있음:
      · fluid_air_core_r01 (포러스) ↔ solid_tube_r01t01 원통면 공유
      · solid_tube (두께 0.65mm) 얇은 솔리드 메싱
      · fluid_ref (관내) 
      · 상·하류 연장 박스
    벤드가 없어 비정형 메싱은 빠짐 → probe() 에서 확인.
    """
    return FTHXParams(
        name="tutorial_1tube",
        tube=TubeSpec(Do=9.52, Di=8.22, L=100, Nr=1, Nt=1,
                      Pt=25.4, Pl=22.0, layout="inline"),
        fin=FinSpec(FPI=14, t_f=0.115, L_fin=80),
        domain=DomainSpec(L_up=40, L_down=80,
                          include_bends=False, include_tube_fluid=True),
        export={"write_pcurves": False},
    )


def probe() -> FTHXParams:
    """관 3개 · 단일 회로(벤드 2개) — 13 바디."""
    return FTHXParams(
        name="probe_small",
        tube=TubeSpec(Do=9.52, Di=8.22, L=100, Nr=1, Nt=3,
                      Pt=25.4, Pl=22.0, layout="inline"),
        fin=FinSpec(FPI=14, t_f=0.115, L_fin=80),
        domain=DomainSpec(L_up=40, L_down=80,
                          include_bends=True, include_tube_fluid=True),
        export={"write_pcurves": False},
    )


PRESETS = {"tutorial": tutorial, "probe": probe}
