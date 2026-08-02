"""프리셋 전체를 out_foam/<프리셋>/ 에 STL 로 내보냄 (검증 루틴 1단계 후반부).

export_stl() 자체가 내장 검증(watertight·면적오차·인벤토리)을 수행하므로
이 스크립트가 예외 없이 끝나면 1단계 통과임.

사용:  python scripts/make_stl.py [프리셋 ...]     (인자 없으면 전체)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fthx import presets                       # noqa: E402
    from fthx.foam_stl import export_stl           # noqa: E402
except ModuleNotFoundError as e:
    print(f"[오류] {e.name} 모듈 없음 — 전역 python 이 아니라 레포 venv 로 실행할 것:\n"
          "  .venv\\Scripts\\python scripts\\make_stl.py\n"
          "  (.venv 이 없으면 run.bat 을 한 번 실행해 생성 — 서버는 Ctrl+C 로 종료)",
          file=sys.stderr)
    sys.exit(2)


def main(names):
    names = names or list(presets.PRESETS)
    for n in names:
        m = export_stl(presets.PRESETS[n](), outdir=f"out_foam/{n}")
        worst = max(b["area_err"] for b in m["bodies"].values())
        print(f"[OK] {n}: {len(m['bodies'])} bodies, "
              f"max area_err {worst:.4%} → out_foam/{n}/")


if __name__ == "__main__":
    main(sys.argv[1:])
