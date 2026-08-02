"""OpenFOAM 케이스 생성 (F1+F2).  사용:  python scripts/make_case.py [tutorial] [출력경로]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fthx import presets
    from fthx.openfoam import write_case
except ModuleNotFoundError as e:
    print(f"[오류] {e.name} 모듈 없음 — 레포 venv 로 실행할 것:\n"
          "  .venv\\Scripts\\python scripts\\make_case.py", file=sys.stderr)
    sys.exit(2)


def main(argv):
    name = argv[0] if argv else "tutorial"
    out = argv[1] if len(argv) > 1 else f"out_foam/case_{name}"
    pl = write_case(presets.PRESETS[name](), out, force=True)
    print(f"[OK] {name} → {out}")
    hw = pl["h_at"][f"level{pl['lv_wall']}"]
    print(f"     h_bg={pl['h_bg_mm']:.3f}mm  level: core={pl['lv_core']} "
          f"ref={pl['lv_ref']} wall={pl['lv_wall']} "
          f"(h@wall={hw:.3f}mm < t_wall={pl['t_wall_mm']:.3f}mm)")
    print(f"     zones: {pl['zones']}")
    print(f"     게이트: Fluent {pl['gate']['fluent_ref_cells']:,} 셀과 같은 자릿수")
    print(f"  다음(WSL): cd <case> && ./Allrun.mesh")


if __name__ == "__main__":
    main(sys.argv[1:])
