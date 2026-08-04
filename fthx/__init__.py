"""FT-HX CFD Studio — 핀-튜브 열교환기 3D 해석 전용 형상 생성 패키지."""
from .params import FTHXParams, TubeSpec, FinSpec, DomainSpec
from . import circuits, distributor, presets, meshing, exporters, closure, post

__version__ = "0.6.0"
__all__ = ["FTHXParams", "TubeSpec", "FinSpec", "DomainSpec",
           "circuits", "distributor", "cad", "presets", "meshing", "exporters", "closure", "post"]
