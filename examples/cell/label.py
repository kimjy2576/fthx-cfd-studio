# -*- coding: utf-8 -*-
# A안 프로브 — 메싱 TUI /boundary/separate/ 로 입출구 존 분리
#
#   fluent 3d -meshing -g -t8 -i label.py   (STAGE=label ./go.sh cell 8)
#
# 기존 cell.msh.h5 을 읽기만 함 — 재메시 불필요. 원본을 덮지 않음.
# 성공 판정: 예외가 아니라 존 수 변화 + 기대 면적(46.08 mm2) 존 출현.

import os
import traceback

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

MESH_IN  = os.path.join(_HERE, r"cell.msh.h5")
MESH_OUT = os.path.join(_HERE, r"cell_labeledA.msh.h5")
SEEDS    = {"cell_inlet": [0.0, 12.7, 1.3894642857142858], "cell_outlet": [176.0, 12.7, 1.3894642857142858]}
INLET_AREA_MM2 = 46.0829     # 구 형상 입구 = 전체 단면 (x=0 엔 핀 없음)
ANGLE    = 40.0                       # 인접 법선차 90도 — 40도면 확실히 갈라짐

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

def _try_all(label, trials):
    print("  == " + label)
    for name, fn in trials:
        try:
            out = fn()
            if out is False or out is None:
                print("    [--] " + name + " -> " + str(out) + " (값 없음)")
                continue
            print("    [OK] " + name + " -> " + str(out)[:200])
            return name, out
        except Exception as e:
            print("    [--] " + name + " : " + type(e).__name__ + ": " + str(e)[:110])
    return None, None

try_all = _try_all

def have(obj, name):
    v = getattr(obj, name, None)
    return v if (v is not None and callable(v)) else None

def _MU():
    g = globals()
    for nm in ("meshing_utilities", "meshing_utilities_app"):
        o = g.get(nm)
        if o is not None:
            return o
    return None

def TUI():
    g = globals()
    for nm in ("PyMenu", "main_menu", "tui"):
        if nm in g and g[nm] is not None:
            return g[nm]
    w = g.get("workflow")
    t = getattr(getattr(w, "_parent", None), "tui", None)
    if t is not None:
        return t
    m = getattr(g.get("meshing"), "tui", None)
    if m is not None:
        return m
    raise NameError("TUI 진입점 없음: " + ", ".join(sorted(
        k for k in g if not k.startswith("_")))[:300])

def TUI_EXEC(cmd):
    g = globals()
    last = None
    for nm in ("meshing", "meshing_app", "session", "root"):
        o = g.get(nm)
        if o is None:
            continue
        for attr in ("execute_tui", "exec_tui", "tui_exec"):
            fn = getattr(o, attr, None)
            if fn is not None:
                try:
                    return fn(cmd)
                except Exception as ex:
                    last = "%s.%s: %s" % (nm, attr, str(ex)[:90])
    raise NameError("execute_tui 경로 없음 (%s)" % last)

# ── 존 조회 (meshing_utilities — 확정 API) ────────────────
def zone_table():
    """[(id, name, area_mm2)] — 면적 단위는 그대로 출력해 실측으로 확정."""
    mu = _MU()
    if mu is None:
        print("    meshing_utilities 없음")
        return []
    ids = mu.get_face_zones(filter="*")
    out = []
    for i in ids:
        try:
            nm = mu.convert_zone_ids_to_name_strings(zone_id_list=[i])
            nm = nm[0] if isinstance(nm, (list, tuple)) and nm else str(nm)
        except Exception:
            nm = "?"
        try:
            ar = mu.get_face_zone_area(face_zone_id_list=[i])
            ar = ar[0] if isinstance(ar, (list, tuple)) and ar else ar
        except Exception:
            ar = None
        out.append((i, nm, ar))
    return out

def dump_zones(tag):
    tz = zone_table()
    print("    [%s] 면 존 %d개" % (tag, len(tz)))
    for i, nm, ar in tz:
        print("      %6s  %-46s area %s" % (i, nm, ar))
    return tz

def near(a, target):
    """면적 단위(mm2/m2)를 모르므로 두 스케일 모두 비교."""
    if a is None:
        return False
    for scale in (1.0, 1e-6):
        t = target * scale
        if t > 0 and abs(a - t) / t < 0.02:
            return True
    return False

step("1. 메시 읽기", lambda: try_all("read-mesh", [
    ("tui file.read_mesh", lambda: TUI().file.read_mesh(MESH_IN)),
    ("exec /file/read-mesh", lambda: TUI_EXEC(
        '/file/read-mesh "%s"' % MESH_IN)),
])[0] or (_ for _ in ()).throw(RuntimeError("메시를 읽지 못함")))

def _dump_menu():
    """추측을 멈추고 실제 메뉴를 본다 — /boundary/separate 하위 전체."""
    try_all("메뉴 덤프", [
        ("exec /boundary/separate", lambda: TUI_EXEC("/boundary/separate q")),
        ("exec /boundary/separate/", lambda: TUI_EXEC("/boundary/separate/")),
    ])
    t = TUI()
    sep = getattr(getattr(t, "boundary", None), "separate", None)
    if sep is not None:
        print("    tui.boundary.separate 하위: %s"
              % [x for x in dir(sep) if not x.startswith("_")])
    else:
        print("    tui.boundary.separate 객체 없음 (문자열 TUI 로만 시도)")
step("2. /boundary/separate 메뉴 확인", _dump_menu)

step("3. 분리 전 존 목록", lambda: dump_zones("before"))

def _find_target(prefix):
    """prefix 바디의 자유면 존(가장 큰 것) — 입구가 묶여 있는 그 존."""
    best = None
    for i, nm, ar in zone_table():
        if not nm.startswith(prefix) or "-solid-" in nm[len(prefix):]:
            continue
        if best is None or (ar or 0) > (best[2] or 0):
            best = (i, nm, ar)
    return best

def _already_split():
    for _i, _nm, ar in zone_table():
        if near(ar, INLET_AREA_MM2):
            return _nm
    return None

def _separate(prefix, seed, label):
    z = _find_target(prefix)
    if z is None:
        print("    [!!] %s 대상 존 없음" % prefix)
        return
    zid, zname, zarea = z
    x, y, w = seed
    print("    대상: id %s  %s  area %s  seed (%g %g %g)"
          % (zid, zname, zarea, x, y, w))
    n0 = len(zone_table())

    def run(cmd):
        TUI_EXEC(cmd)
        n1 = len(zone_table())
        print("      존 수 %d -> %d" % (n0, n1))
        return n1 > n0        # 존이 늘어야 성공 — 조용한 실패 방지

    t = TUI()
    sep = getattr(getattr(t, "boundary", None), "separate", None)

    def run_obj(fn_name, *args):
        fn = have(sep, fn_name) if sep is not None else None
        if fn is None:
            return False
        fn(*args)
        n1 = len(zone_table())
        print("      존 수 %d -> %d" % (n0, n1))
        return n1 > n0

    try_all("%s seed 분리" % label, [
        ("seed-angle id str", lambda: run(
            "/boundary/separate/sep-face-zone-by-seed-angle %s %g %g %g %g"
            % (zid, x, y, w, ANGLE))),
        ("seed id str", lambda: run(
            "/boundary/separate/sep-face-zone-by-seed %s %g %g %g"
            % (zid, x, y, w))),
        ("seed-angle name str", lambda: run(
            '/boundary/separate/sep-face-zone-by-seed-angle "%s" %g %g %g %g'
            % (zname, x, y, w, ANGLE))),
        ("seed name str", lambda: run(
            '/boundary/separate/sep-face-zone-by-seed "%s" %g %g %g'
            % (zname, x, y, w))),
        ("obj seed_angle", lambda: run_obj(
            "sep_face_zone_by_seed_angle", zid, x, y, w, ANGLE)),
        ("obj seed", lambda: run_obj("sep_face_zone_by_seed", zid, x, y, w)),
        ("angle id str (차선)", lambda: run(
            "/boundary/separate/sep-face-zone-by-angle %s %g" % (zid, ANGLE))),
    ])

def _separations():
    hit = _already_split()
    if hit:
        print("    기대 면적 존이 이미 있음: %s — 분리 불필요 (새 형상 메시?)" % hit)
        return
    _separate("fluid_cell_up",   SEEDS["cell_inlet"],  "입구")
    _separate("fluid_cell_down", SEEDS["cell_outlet"], "출구")
step("4. seed 분리 시도", _separations)

def _after():
    tz = dump_zones("after")
    hits = [(i, nm, ar) for i, nm, ar in tz if near(ar, INLET_AREA_MM2)]
    print("    기대 면적(%.2f mm2) 일치 존 %d개: %s"
          % (INLET_AREA_MM2, len(hits), [h[1] for h in hits]))
step("5. 분리 후 존 목록 + 면적 판정", _after)

def _rename():
    """면적이 맞는 조각을 seed x 좌표로 입/출구 구분해 개명."""
    mu = _MU()
    if mu is None:
        print("    meshing_utilities 없음 — 개명 생략")
        return
    hits = [(i, nm, ar) for i, nm, ar in zone_table()
            if near(ar, INLET_AREA_MM2)]
    if len(hits) != 2:
        print("    [!!] 후보 %d개 (2개여야 함) — 개명 보류, 로그로 판단" % len(hits))
        return
    # up 바디 조각 = 입구(x=0), down 바디 조각 = 출구(x=Lx)
    for i, nm, _ar in hits:
        dst = "cell_inlet" if nm.startswith("fluid_cell_up") else "cell_outlet"
        try_all("%s -> %s" % (nm, dst), [
            ("rename_face_zone", lambda a=nm, b=dst:
                mu.rename_face_zone(zone_name=a, new_name=b) or True),
        ])
step("6. 개명", _rename)

step("7. 저장 (원본 보존, 별도 파일)", lambda: try_all("write-mesh", [
    ("tui file.write_mesh", lambda: TUI().file.write_mesh(MESH_OUT)),
    ("exec /file/write-mesh", lambda: TUI_EXEC(
        '/file/write-mesh "%s"' % MESH_OUT)),
]))

def _verify():
    import time
    for f in (MESH_IN, MESH_OUT):
        if os.path.exists(f):
            st = os.stat(f)
            print("    [OK] %-24s %8.2f MB  %s" % (
                os.path.basename(f), st.st_size / 1e6,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
        else:
            print("    [!!] %-24s 없음" % os.path.basename(f))
step("8. 파일 확인", _verify)

print("=" * 60)
print("LABEL 완료")
print("=" * 60)
try:
    TUI().exit()
except Exception:
    try:
        TUI_EXEC("/exit yes")
    except Exception:
        pass
