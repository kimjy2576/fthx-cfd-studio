"""미리 정의된 케이스.

tutorial : 관 1개. Fluent 메싱을 처음 시험할 때 쓰는 최소 케이스.
probe    : 관 3개 + 벤드 2개. 튜토리얼 통과 후 벤드 메싱을 확인할 때.
"""
from __future__ import annotations

from .params import FTHXParams, TubeSpec, FinSpec, DomainSpec, DuctSpec


def tutorial() -> FTHXParams:
    """관 1개 · 벤드 없음 — 5 바디.

    구조적으로 확인해야 할 것은 다 들어 있음:
      · fluid_air_core_r01 (포러스) ↔ solid_tube_r01t01 원통면 공유
      · solid_tube (두께 0.65mm) 얇은 솔리드 메싱
      · fluid_ref (관내)
      · 상·하류 연장 박스

    의도적으로 **가장 쉬운 조건**으로 둠 — 핀팩이 관 전장을 채우므로(L_fin=L)
    관 외벽 원통면과 코어 구멍면이 **정확히 일치**함. 즉 Share Topology 가
    imprint 없이 바로 붙어야 함. 여기서 안 붙으면 설정 문제임.

    핀팩이 관보다 짧은 실제 조건(면 길이가 달라 imprint 필요)과 벤드
    비정형 메싱은 probe() 에서 확인.
    """
    return FTHXParams(
        name="tutorial_1tube",
        tube=TubeSpec(Do=9.52, Di=8.22, L=100, Nr=1, Nt=1,
                      Pt=25.4, Pl=22.0, layout="inline"),
        fin=FinSpec(FPI=14, t_f=0.115),        # L_fin=None → 관 전장 = 100
        domain=DomainSpec(L_up=40, L_down=80,
                          include_bends=False, include_tube_fluid=True),
        duct=DuctSpec(wall_t=2.0),      # 케이싱 — 입출구 면이 단독 존이 되게 함
        export={"write_pcurves": False},
    )


def probe() -> FTHXParams:
    """관 3개 · 단일 회로(벤드 2개) — 13 바디.

    튜토리얼보다 어려운 조건을 일부러 넣음:
      · L_fin(80) < L(100) → 관 외벽 면이 코어 구멍면보다 길어 imprint 필요
      · 벤드 2개 → 비정형(poly/tet) 메싱
    """
    return FTHXParams(
        name="probe_small",
        tube=TubeSpec(Do=9.52, Di=8.22, L=100, Nr=1, Nt=3,
                      Pt=25.4, Pl=22.0, layout="inline"),
        fin=FinSpec(FPI=14, t_f=0.115, L_fin=80),
        domain=DomainSpec(L_up=40, L_down=80,
                          include_bends=True, include_tube_fluid=True),
        duct=DuctSpec(wall_t=2.0),      # 케이싱 — 입출구 면이 단독 존이 되게 함
        export={"write_pcurves": False},
    )


def cell() -> FTHXParams:
    """주기 단위셀용 — 2열이면 staggered 패턴이 한 번 반복돼 충분함.
       열을 늘리면 셀만 커지고 j·f 는 거의 같음(입구 효과 제외)."""
    return FTHXParams(
        name="cell_plain",
        tube=TubeSpec(Do=9.52, Di=8.22, L=100, Nr=2, Nt=1,
                      Pt=25.4, Pl=22.0, layout="staggered"),
        fin=FinSpec(FPI=14, t_f=0.115, fin_type="plain"),
        domain=DomainSpec(include_bends=False, include_tube_fluid=False),
        export={"write_pcurves": False},
    )


PRESETS = {"tutorial": tutorial, "probe": probe, "cell": cell}
