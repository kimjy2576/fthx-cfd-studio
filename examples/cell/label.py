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
    """추측을 멈추고 실제를 본다 — separate 메뉴 + 오브젝트 세계.

    v1 실측(2579688): 명령 9종이 전부 실재하는데 7개 인자 변형이 모두
    존 수 27->27 로 조용히 실패. 가설 2개를 이번에 가름:
      (a) 인자/프롬프트 형식 불일치 ("Invalid entity")
      (b) watertight 산출물이라 존이 mesh object 소유 — /boundary/ 직접
          조작 거부, /objects/ 경로로 가야 함"""
    try_all("메뉴 덤프", [
        ("exec /boundary/separate", lambda: TUI_EXEC("/boundary/separate q")),
    ])
    t = TUI()
    sep = getattr(getattr(t, "boundary", None), "separate", None)
    if sep is not None:
        print("    tui.boundary.separate 하위: %s"
              % [x for x in dir(sep) if not x.startswith("_")])
    obj = getattr(t, "objects", None)
    if obj is not None:
        print("    tui.objects 하위(sep 관련): %s"
              % [x for x in dir(obj) if "sep" in x or "list" in x])
    # 오브젝트 소유 가설 (b) 검증 — 오브젝트 목록
    mu = _MU()
    try_all("오브젝트 목록", [
        ("mu.get_all_object_name_list", lambda:
            mu.get_all_object_name_list() if mu else None),
        ("mu.get_object_name_list_of_type mesh", lambda:
            mu.get_object_name_list_of_type(object_type="mesh") if mu else None),
        ("exec /objects/list-objects", lambda:
            TUI_EXEC("/objects/list-objects") or True),
    ])
step("2. 메뉴 + 오브젝트 세계 확인", _dump_menu)

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

WINNER = []      # 입구에서 찾은 레시피를 출구에 재사용

def _variants(zid, zname, x, y, w, box):
    """(이름, 실행자) 목록 — v1 에서 전부 실패한 형식은 뺐음.

    v1 오류 "Invalid entity. Error object: 29" 는 인자가 토큰별로
    거부된 것 — 리스트 문법 (id), 비인용 이름, yes 종결, 그리고
    entity 문법을 아예 우회하는 mark 경로(좌표 박스)를 추가."""
    t = TUI()
    sep = getattr(getattr(t, "boundary", None), "separate", None)
    obj = getattr(t, "objects", None)
    V = []

    def S(name, cmd):
        V.append((name, ("cmd", cmd)))

    # ── (a) 인자 형식 변형 ──
    S("angle 리스트 (id)", "/boundary/separate/sep-face-zone-by-angle (%s) %g yes"
      % (zid, ANGLE))
    S("angle 리스트 (이름)", "/boundary/separate/sep-face-zone-by-angle (%s) %g yes"
      % (zname, ANGLE))
    S("angle 이름 비인용", "/boundary/separate/sep-face-zone-by-angle %s %g yes"
      % (zname, ANGLE))
    S("seed 리스트+좌표", "/boundary/separate/sep-face-zone-by-seed (%s) %g %g %g"
      % (zid, x, y, w))
    S("seed 이름 비인용", "/boundary/separate/sep-face-zone-by-seed %s %g %g %g"
      % (zname, x, y, w))
    # ── (a2) mark 경로 — entity 문법 우회, 좌표 박스로 마킹 후 분리 ──
    x0, x1, y0, y1, z0, z1 = box
    V.append(("mark 3연타(정의-마킹-분리)", ("mark",
        ["/boundary/separate/local-regions/define inlet-box box %g %g %g %g %g %g"
         % (x0, x1, y0, y1, z0, z1),
         "/boundary/separate/local-regions/define inlet-box box (%g %g %g) (%g %g %g)"
         % (x0, y0, z0, x1, y1, z1),
         "/boundary/separate/mark-faces-in-region %s inlet-box yes" % zid,
         "/boundary/separate/mark-faces-in-region (%s) inlet-box yes" % zid,
         "/boundary/separate/sep-face-zone-by-mark %s yes" % zid,
         "/boundary/separate/sep-face-zone-by-mark (%s) yes" % zid])))
    # ── (b) 오브젝트 경로 ──
    if obj is not None:
        for fn_nm in ("separate_faces_by_seed", "separate_faces_by_angle"):
            fn = have(obj, fn_nm)
            if fn is None:
                continue
            if "seed" in fn_nm:
                V.append(("objects.%s" % fn_nm, ("call", fn, ("*", x, y, w))))
            else:
                V.append(("objects.%s" % fn_nm, ("call", fn, ("*", ANGLE))))
    if sep is not None:
        fn = have(sep, "sep_face_zone_by_angle")
        if fn is not None:
            V.append(("obj sep_by_angle(id,ANGLE)", ("call", fn, (zid, ANGLE))))
    return V

def _run_variant(kind_payload, n0):
    kind = kind_payload[0]
    if kind == "cmd":
        cmd = kind_payload[1]
        print("      cmd: %s" % cmd)           # 오류문 귀속용 marker
        TUI_EXEC(cmd)
    elif kind == "mark":
        for cmd in kind_payload[1]:
            print("      cmd: %s" % cmd)
            try:
                TUI_EXEC(cmd)
            except Exception as e:
                print("      (계속) %s: %s" % (type(e).__name__, str(e)[:90]))
    elif kind == "call":
        fn, args = kind_payload[1], kind_payload[2]
        print("      call: %s%s" % (getattr(fn, "__name__", fn), args))
        fn(*args)
    n1 = len(zone_table())
    print("      존 수 %d -> %d" % (n0, n1))
    return n1 > n0        # 존이 늘어야 성공 — 조용한 실패 방지

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
    # seed 를 감싸는 작은 박스 (면 두께 방향 여유 ±0.3mm)
    box = (x - 0.3, x + 0.3, -1.0, 30.0, -1.0, 3.0)
    if WINNER:
        nm = WINNER[0]
        vs = [(n, pl) for n, pl in _variants(zid, zname, x, y, w, box) if n == nm]
        print("    입구에서 찾은 레시피 재사용: %s" % nm)
    else:
        vs = _variants(zid, zname, x, y, w, box)
    won, _ = try_all("%s 분리" % label,
                     [(n, (lambda pl=pl: _run_variant(pl, n0)))
                      for n, pl in vs])
    if won and not WINNER:
        WINNER.append(won)

def _separations():
    hit = _already_split()
    if hit:
        print("    기대 면적 존이 이미 있음: %s — 분리 불필요 (새 형상 메시?)" % hit)
        return
    _separate("fluid_cell_up",   SEEDS["cell_inlet"],  "입구")
    _separate("fluid_cell_down", SEEDS["cell_outlet"], "출구")
step("4. 분리 시도 (형식 변형 + mark + objects)", _separations)

def _after():
    tz = dump_zones("after")
    hits = [(i, nm, ar) for i, nm, ar in tz if near(ar, INLET_AREA_MM2)]
    print("    기대 면적(%.2f mm2) 일치 존 %d개: %s"
          % (INLET_AREA_MM2, len(hits), [h[1] for h in hits]))
step("5. 분리 후 존 목록 + 면적 판정", _after)

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
step("6. 개명", _rename)

def _save():
    """개명까지 성공했을 때만 저장 — 270MB 무의미 재저장 방지 (v1 교훈)."""
    if len(RENAMED) != 2:
        print("    개명 %d/2 — 저장 생략 (프로브 결과는 로그로 판단)" % len(RENAMED))
        return
    try_all("write-mesh", [
        ("tui file.write_mesh", lambda: TUI().file.write_mesh(MESH_OUT)),
        ("exec /file/write-mesh", lambda: TUI_EXEC(
            '/file/write-mesh "%s"' % MESH_OUT)),
    ])
step("7. 저장 (개명 성공시에만, 원본 보존)", _save)

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
