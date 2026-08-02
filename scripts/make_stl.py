"""프리셋 전체를 out_foam/<프리셋>/ 에 STL 로 내보냄 (검증 루틴 1단계 후반부).

export_stl() 자체가 내장 검증(watertight·면적오차·인벤토리)을 수행하므로
이 스크립트가 예외 없이 끝나면 1단계 통과임.

사용:  python scripts/make_stl.py [프리셋 ...]     (인자 없으면 전체)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fthx import presets                       # noqa: E402
from fthx.foam_stl import export_stl           # noqa: E402


def main(names):
    names = names or list(presets.PRESETS)
    for n in names:
        m = export_stl(presets.PRESETS[n](), outdir=f"out_foam/{n}")
        worst = max(b["area_err"] for b in m["bodies"].values())
        print(f"[OK] {n}: {len(m['bodies'])} bodies, "
              f"max area_err {worst:.4%} → out_foam/{n}/")


if __name__ == "__main__":
    main(sys.argv[1:])
