# -*- coding: utf-8 -*-
# B안 프로브 — 솔버 sep-face-zone-angle ("by" 없는 정식 명령명)
#
#   fluent 3ddp -g -t8 -i sep_solver.py
#
# 읽기만 함 — 저장 없음. 성공 판정 = wall 존 수 증가 + 46.08mm2 조각.

import os
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

MESH_IN = os.path.join(_HERE, r"cell.msh.h5")
ANGLE   = 40.0
INLET_AREA_MM2 = 46.0829

def step(label, fn):
    print("=" * 60)
    print(">>> " + label)
    try:
        fn()
        print("<<< OK   " + label)
        return True
    except Exception as e:
        print("<<< FAIL " + label + " : " + type(e).__name__ + ": " + str(e)[:300])
        traceback.print_exc()
        return False

def TUI():
    g = globals()
    for nm in ("tui", "solver", "session", "root"):
        o = g.get(nm)
        if o is None:
            continue
        if nm == "tui":
            return o
        t = getattr(o, "tui", None)
        if t is not None:
            return t
    raise NameError("TUI 진입점 없음")

def SETTINGS():
    g = globals()
    for nm in ("solver", "session", "root"):
        o = g.get(nm)
        if o is not None and getattr(o, "settings", None) is not None:
            return o.settings
    raise NameError("settings 없음")

def try_all(label, trials):
    print("  == " + label)
    for name, fn in trials:
        try:
            out = fn()
            if out is False or out is None:
                print("    [--] " + name + " -> " + str(out))
                continue
            print("    [OK] " + name)
            return name, out
        except Exception as ex:
            print("    [--] " + name + " : " + type(ex).__name__ + ": " + str(ex)[:110])
    return None, None

step("1. 메시 읽기", lambda: TUI().file.read_case(MESH_IN) or True)

def _walls():
    S = SETTINGS()
    return [w for w in list(S.setup.boundary_conditions.wall)
            if not w.endswith("-shadow")]

def _dump(tag):
    ws = _walls()
    print("    [%s] wall %d개" % (tag, len(ws)))
    for w in ws:
        print("      %s" % w)
    return ws

step("2. 분리 전 wall 목록", lambda: _dump("before"))

def _mz():
    """settings 쪽 modify_zones 유무 + 하위 실물 덤프."""
    S = SETTINGS()
    mz = getattr(getattr(S, "mesh", None), "modify_zones", None)
    if mz is None:
        print("    settings.mesh.modify_zones 없음 (25.1 미승격일 수 있음)")
        return
    subs = [x for x in dir(mz) if "sep" in x or x in ("zone_name", "zone_type",
                                                      "make_periodic")]
    print("    settings.mesh.modify_zones 하위(발췌): %s" % subs)
step("3. settings modify_zones 실물", _mz)

WINNER = []

def _sep(zone, label):
    n0 = len(_walls())
    print("    대상: %s  (wall %d개)" % (zone, n0))
    t = TUI()
    S = SETTINGS()
    mz_t = getattr(getattr(t, "mesh", None), "modify_zones", None)
    mz_s = getattr(getattr(S, "mesh", None), "modify_zones", None)

    def chk(_ret):
        n1 = len(_walls())
        print("      존 수 %d -> %d" % (n0, n1))
        return n1 > n0

    trials = [
        ("tui sep_face_zone_angle(name,ANGLE)", lambda:
            chk(mz_t.sep_face_zone_angle(zone, ANGLE)) if mz_t else False),
        ("settings sep_face_zone_angle(name,ANGLE)", lambda:
            chk(mz_s.sep_face_zone_angle(face_zone_name=zone, angle=ANGLE))
            if mz_s else False),
        ("settings +move_faces=False", lambda:
            chk(mz_s.sep_face_zone_angle(face_zone_name=zone, angle=ANGLE,
                                         move_faces=False)) if mz_s else False),
        ("settings +move_faces=True", lambda:
            chk(mz_s.sep_face_zone_angle(face_zone_name=zone, angle=ANGLE,
                                         move_faces=True)) if mz_s else False),
    ]
    if WINNER:
        trials = [(n, f) for n, f in trials if n == WINNER[0]]
        print("    입구에서 찾은 레시피 재사용: %s" % WINNER[0])
    won, _ = try_all("%s 분리" % label, trials)
    if won and not WINNER:
        WINNER.append(won)

step("4. 분리 시도 (입구 존)",
     lambda: _sep("fluid_cell_up-solid:1", "입구"))
step("5. 분리 시도 (출구 존)",
     lambda: _sep("fluid_cell_down-solid:1", "출구"))

def _areas():
    """분리 조각 면적 — 46.08mm2(=4.608e-5 m2) 조각이 입구.
    v1(2578722)에서 면적을 19존 전부 얻어낸 것과 동일한 TUI 체인."""
    t = TUI()
    si = getattr(getattr(t, "report", None), "surface_integrals", None)
    tmp = os.path.join(_HERE, "_a.txt")

    def area_of(zone):
        fn = getattr(si, "area", None) if si else None
        if fn is None:
            return None
        if os.path.exists(tmp):
            os.remove(tmp)
        for args in ((zone, "()", "yes", tmp, "yes"),
                     (zone, "()", "yes", tmp),
                     (zone, "yes", tmp)):
            try:
                fn(*args)
                break
            except Exception:
                continue
        try:
            for line in open(tmp).read().splitlines():
                for tok in line.split()[::-1]:
                    try:
                        return float(tok)
                    except ValueError:
                        continue
        except Exception:
            return None
        return None

    hits = []
    for w in _dump("after"):
        if "fluid_cell_up" not in w and "fluid_cell_down" not in w:
            continue
        a = area_of(w)
        print("      %-46s area %s" % (w, a))
        if a is not None and any(
                abs(a - INLET_AREA_MM2 * s) / (INLET_AREA_MM2 * s) < 0.02
                for s in (1.0, 1e-6)):
            hits.append(w)
    print("    기대 면적(%.2f mm2) 일치 존 %d개: %s"
          % (INLET_AREA_MM2, len(hits), hits))
step("6. 조각 면적 판정", _areas)

print("=" * 60)
print("BSEP 완료 (프로브 — 저장 없음)")
print("=" * 60)
try:
    TUI().exit("yes")
except Exception:
    try:
        TUI().exit()
    except Exception:
        pass
