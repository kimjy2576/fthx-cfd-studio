# -*- coding: utf-8 -*-
# M2 라벨링 (A안) — 메싱 TUI 각도분리로 입출구 존 분리·개명
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
MESH_OUT = os.path.join(_HERE, r"cell_labeled.msh.h5")
INLET_AREA_MM2 = 46.0829     # 입구 = 전체 단면 Ly x Lz (x=0 엔 핀 없음)
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

step("2. 분리 전 존 목록", lambda: dump_zones("before"))

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

def _separate(prefix, label):
    """검증된 레시피(2580749): sep-face-zone-by-angle **(id)** ANGLE yes.

    각도분리라 입구 + 측면 4개가 모두 제 존으로 갈라짐 (법선차 90도).
    어느 조각이 입구인지는 면적(기대 46.08 mm2)으로 뒤에서 판정."""
    z = _find_target(prefix)
    if z is None:
        print("    [!!] %s 대상 존 없음" % prefix)
        return
    zid, zname, zarea = z
    print("    대상: id %s  %s  area %s" % (zid, zname, zarea))
    n0 = len(zone_table())
    cmd = "/boundary/separate/sep-face-zone-by-angle (%s) %g yes" % (zid, ANGLE)
    print("      cmd: %s" % cmd)
    TUI_EXEC(cmd)
    n1 = len(zone_table())
    print("      존 수 %d -> %d" % (n0, n1))
    if n1 <= n0:
        raise RuntimeError("%s 분리 실패 — 존 수 불변 (%d)" % (prefix, n0))

def _separations():
    hit = _already_split()
    if hit:
        print("    기대 면적 존이 이미 있음: %s — 분리 생략" % hit)
        return
    _separate("fluid_cell_up",   "입구")
    _separate("fluid_cell_down", "출구")
step("3. 각도분리 (검증된 리스트 문법)", _separations)

def _after():
    tz = dump_zones("after")
    hits = [(i, nm, ar) for i, nm, ar in tz if near(ar, INLET_AREA_MM2)]
    print("    기대 면적(%.2f mm2) 일치 존 %d개: %s"
          % (INLET_AREA_MM2, len(hits), [h[1] for h in hits]))
step("4. 분리 후 존 목록 + 면적 판정", _after)

RENAMED = []

def _rename():
    """면적이 맞는 조각을 바디 이름으로 입/출구 구분해 개명."""
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
        won, _ = try_all("%s -> %s" % (nm, dst), [
            ("rename_face_zone", lambda a=nm, b=dst:
                mu.rename_face_zone(zone_name=a, new_name=b) or True),
        ])
        if won:
            RENAMED.append(dst)
step("5. 개명", _rename)

def _save():
    """개명 2/2 일 때만 저장. 기존 파일은 먼저 지움 — write_mesh 가
    overwrite 프롬프트에 걸리면 [OK] 를 돌려주고도 실제로는 저장하지
    않음 (실측 2580749: mtime 불변)."""
    if len(RENAMED) != 2:
        raise RuntimeError("개명 %d/2 — 저장 중단" % len(RENAMED))
    if os.path.exists(MESH_OUT):
        os.remove(MESH_OUT)
        print("    기존 %s 삭제 (프롬프트 회피)" % os.path.basename(MESH_OUT))
    try_all("write-mesh", [
        ("tui file.write_mesh", lambda: TUI().file.write_mesh(MESH_OUT)),
        ("exec /file/write-mesh", lambda: TUI_EXEC(
            '/file/write-mesh "%s"' % MESH_OUT)),
    ])
    import time
    st = os.stat(MESH_OUT) if os.path.exists(MESH_OUT) else None
    if st is None or (time.time() - st.st_mtime) > 300:
        raise RuntimeError("저장 검증 실패 — %s 가 새로 쓰이지 않음" % MESH_OUT)
step("6. 저장 (개명 2/2 시에만 · 프롬프트 회피)", _save)

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
step("7. 파일 확인", _verify)

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
