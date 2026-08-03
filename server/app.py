"""
FT-HX CFD Studio — 로컬 서버

    python run.py           →  http://127.0.0.1:8020

정적 스튜디오(web/index.html)를 서빙하고, 브라우저에서 만든 형상·회로를
그대로 STEP 으로 뽑을 수 있는 API 를 제공함.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import fthx
from fthx import (FTHXParams, circuits as CQC, distributor as DST,
                  presets, meshing, exporters)

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

app = FastAPI(title="FT-HX CFD Studio", version=fthx.__version__)


# ══════════════════════════════════════════════════════════════════
#  요청 모델
# ══════════════════════════════════════════════════════════════════
class CircuitIn(BaseModel):
    id: str
    tubes: List[int]
    inlet_end: str = "z0"
    m_frac: Optional[float] = None


class CaseIn(BaseModel):
    """스튜디오가 내보내는 case.json 의 부분집합"""
    name: str = "fthx_case"
    tube: Dict[str, Any]
    fin: Dict[str, Any]
    domain: Dict[str, Any] = Field(default_factory=dict)
    circuits: Optional[Dict[str, Any]] = None

    def to_params(self) -> FTHXParams:
        return FTHXParams(name=self.name, tube=self.tube, fin=self.fin,
                          domain=self.domain or {})

    def to_circuits(self) -> Optional[CQC.CircuitSet]:
        """스튜디오는 circuits.list, API 응답은 circuits.circuits — 둘 다 수용"""
        if not self.circuits:
            return None
        raw = self.circuits.get("list") or self.circuits.get("circuits")
        if not raw:
            return None
        return CQC.CircuitSet(
            pattern=self.circuits.get("pattern", "custom"),
            circuits=[CQC.Circuit(**c) for c in raw])


class GenIn(BaseModel):
    case: CaseIn
    pattern: str = "face_split"
    n_circuit: int = 4
    inlet_end: str = "z0"
    reverse: bool = False          # 생성 후 유동 방향 반전


class DistIn(BaseModel):
    case: CaseIn
    fluid: str = "R410A"
    T_C: float = 7.0
    quality: float = 1.0
    rho: Optional[float] = None
    mu: Optional[float] = None
    m_total_kgs: float = 0.03
    K_bend: float = 0.7
    plenum: Dict[str, Any] = Field(default_factory=dict)


class ExportIn(BaseModel):
    case: CaseIn
    with_plenum: bool = False
    plenum: Dict[str, Any] = Field(default_factory=dict)
    fluid: Optional[DistIn] = None


# ══════════════════════════════════════════════════════════════════
#  API
# ══════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════
#  앱 업데이트 (git pull)
# ══════════════════════════════════════════════════════════════════
def _git(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    """git 실행.

    · GIT_TERMINAL_PROMPT=0 : 인증 프롬프트에서 멈추지 않게
    · encoding='utf-8', errors='replace' : 한글 커밋 메시지가 있을 때
      Windows 기본 로케일(cp949)로 디코드하다 UnicodeDecodeError 로
      500 이 나던 문제를 막음. text=True 만 쓰면 로케일에 좌우됨.
    """
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C.UTF-8",
               GIT_OPTIONAL_LOCKS="0")
    env.pop("GIT_ASKPASS", None)          # Windows 에서 echo 는 실행파일이 아님
    try:
        r = subprocess.run(["git", *args], cwd=str(ROOT), env=env,
                           capture_output=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "git 실행 파일을 찾을 수 없음 (PATH 확인)"
    except subprocess.TimeoutExpired:
        return 124, "", f"git {' '.join(args)} 시간 초과({timeout}s)"
    except Exception as e:                # 예상 못 한 것도 500 대신 메시지로
        return 1, "", f"{type(e).__name__}: {e}"


def _git_state() -> dict:
    ok, head, _ = _git("rev-parse", "--short", "HEAD")
    if ok != 0:
        return {"is_repo": False}
    _, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    _, dirty, _ = _git("status", "--porcelain")
    _, subj, _ = _git("log", "-1", "--pretty=%s")
    rc, upstream, _ = _git("rev-parse", "--abbrev-ref", "@{u}")
    return {"is_repo": True, "commit": head, "branch": branch,
            "subject": subj, "upstream": upstream if rc == 0 else None,
            "dirty": [l for l in dirty.splitlines() if l][:20],
            "reload_mode": os.environ.get("FTHX_RELOAD") == "1"}


@app.get("/api/version")
def version():
    return {"version": app.version, "git": _git_state()}


@app.post("/api/update")
def update():  # noqa: C901
    """git pull --ff-only 로 최신 코드를 받아옴.

    - 로컬 수정이 있으면 덮어쓰지 않고 거부함
    - --ff-only 라 병합 충돌이 생기지 않음
    - 파이썬 모듈은 이미 임포트돼 있어 코드 변경은 서버 재시작이 필요함
      (python run.py --reload 로 띄웠으면 자동 재시작됨)
    """
    try:
        return _do_update()
    except HTTPException:
        raise
    except Exception as e:                # 예상 못 한 예외를 구조화해 반환
        import traceback
        raise HTTPException(500, {"message": f"{type(e).__name__}: {e}",
                                  "trace": traceback.format_exc()[-800:]})


def _do_update():
    st = _git_state()
    if not st.get("is_repo"):
        raise HTTPException(400, "git 저장소가 아님 — zip 으로 받은 경우 업데이트 불가")
    if st["upstream"] is None:
        raise HTTPException(400, f"'{st['branch']}' 에 추적 원격이 없음 "
                                 "(git branch --set-upstream-to=origin/main)")
    if st["dirty"]:
        raise HTTPException(409, {"message": "로컬 수정 사항이 있어 중단함 "
                                             "(덮어쓰지 않음). 커밋하거나 되돌린 뒤 재시도",
                                  "dirty": st["dirty"]})

    rc, _, err = _git("fetch", "--quiet")
    if rc != 0:
        raise HTTPException(502, f"fetch 실패 (인증·네트워크 확인): {err[:300]}")

    _, ahead, _ = _git("rev-list", "--count", "@{u}..HEAD")
    _, behind, _ = _git("rev-list", "--count", "HEAD..@{u}")
    if ahead not in ("", "0") and behind not in ("", "0"):
        raise HTTPException(409, {
            "message": f"브랜치가 갈라졌음 (로컬 {ahead}개 앞, 원격 {behind}개 뒤) — "
                       "fast-forward 불가. 로컬 커밋을 푸시하거나 되돌린 뒤 재시도",
            "ahead": int(ahead), "behind": int(behind)})
    if behind in ("", "0"):
        return {"updated": False, "message": "이미 최신 버전임",
                "before": st["commit"], "after": st["commit"], "git": _git_state()}

    _, log, _ = _git("log", "--oneline", "HEAD..@{u}")
    rc, out, err = _git("pull", "--ff-only")
    if rc != 0:
        raise HTTPException(500, {"message": "git pull --ff-only 실패",
                                  "returncode": rc,
                                  "stderr": err[:600], "stdout": out[:600]})

    after = _git_state()
    return {"updated": True, "behind": int(behind),
            "message": f"{behind}개 커밋 적용됨",
            "commits": log.splitlines()[:20],
            "before": st["commit"], "after": after["commit"],
            "restart_required": not after["reload_mode"],
            "git": after}


@app.get("/api/health")
def health():
    try:
        import cadquery  # noqa: F401
        cad_ok = True
    except Exception:
        cad_ok = False
    return {"ok": True, "version": app.version,
            "cadquery": cad_ok, "coolprop": DST.HAS_CP}


@app.post("/api/circuits/generate")
def gen_circuits(req: GenIn):
    p = req.case.to_params()
    g = CQC.GENERATORS.get(req.pattern)
    if g is None:
        raise HTTPException(400, f"unknown pattern: {req.pattern}")
    cs = (g(p, req.n_circuit, req.inlet_end)
          if req.pattern in ("face_split", "interlaced")
          else g(p, req.inlet_end))
    if req.reverse:
        cs = CQC.reverse_all(cs)
    return {"circuits": cs.model_dump(), **CQC.build(p, cs)}


class RevIn(BaseModel):
    case: CaseIn
    circuits: Optional[List[str]] = None   # None → 전체 반전


@app.post("/api/circuits/reverse")
def reverse_circuits(req: RevIn):
    """유동 방향 반전. 벤드 형상은 그대로고 입출구만 맞바뀜."""
    p = req.case.to_params()
    cs = req.case.to_circuits()
    if cs is None:
        raise HTTPException(400, "circuits 가 비어 있음")
    rv = CQC.apply_reverse(cs, req.circuits)
    return {"circuits": rv.model_dump(), **CQC.build(p, rv)}


@app.post("/api/circuits/validate")
def validate_circuits(req: CaseIn):
    p = req.to_params()
    cs = req.to_circuits()
    if cs is None:
        raise HTTPException(400, "circuits.list 가 비어 있음")
    return CQC.build(p, cs)


@app.post("/api/distribution")
def distribution(req: DistIn):
    p = req.case.to_params()
    cs = req.case.to_circuits() or CQC.gen_row_serpentine(p)
    pl = DST.PlenumSpec(**req.plenum)
    fl = DST.Fluid(name=req.fluid, T_C=req.T_C, quality=req.quality,
                   rho=req.rho, mu=req.mu)
    legs = DST.legs_from_circuits(p, cs, pl)
    before = DST.solve_split(legs, req.m_total_kgs, p, pl, fl, req.K_bend)
    jumps = DST.size_jumps(legs, req.m_total_kgs, p, pl, fl, req.K_bend)
    after = DST.solve_split(legs, req.m_total_kgs, p, pl, fl, req.K_bend)
    return {"before": before, "jump_sizing": jumps, "after": after}


@app.post("/api/export/step")
def export_step(req: ExportIn):
    try:
        from fthx import cad as CAD
    except Exception as e:                                   # pragma: no cover
        raise HTTPException(503, f"cadquery 미설치: {e}")
    p = req.case.to_params()
    cs = req.case.to_circuits()
    pl = DST.PlenumSpec(**req.plenum) if req.with_plenum else None
    fl = m = None
    if req.fluid is not None:
        fl = DST.Fluid(name=req.fluid.fluid, T_C=req.fluid.T_C,
                       quality=req.fluid.quality, rho=req.fluid.rho, mu=req.fluid.mu)
        m = req.fluid.m_total_kgs
    out = Path(tempfile.mkdtemp())
    meta = CAD.export(p, outdir=str(out), cs=cs, plenum=pl,
                      fluid=fl, m_total=m or 0.0)
    return FileResponse(meta["_files"]["step"], media_type="model/step",
                        filename=f"{p.name}.step")


@app.post("/api/export/meta")
def export_meta(req: ExportIn):
    from fthx import cad as CAD
    p = req.case.to_params()
    cs = req.case.to_circuits()
    pl = DST.PlenumSpec(**req.plenum) if req.with_plenum else None
    out = Path(tempfile.mkdtemp())
    meta = CAD.export(p, outdir=str(out), cs=cs, plenum=pl)
    meta.pop("_files", None)
    return JSONResponse(meta)


# ══════════════════════════════════════════════════════════════════
#  튜토리얼 / 시험 케이스
# ══════════════════════════════════════════════════════════════════
PRESET_INFO = {
    "tutorial": {"label": "튜토리얼 · 관 1개", "bodies": 5,
                 "desc": "벤드 없음. 포러스↔관벽 conformal 접합과 얇은 관벽 "
                         "메싱을 확인하는 최소 케이스"},
    "probe":    {"label": "시험 · 관 3개", "bodies": 13,
                 "desc": "단일 회로(벤드 2개). 비정형 벤드 메싱까지 확인"},
}


@app.get("/api/preset")
def preset_list():
    out = []
    for k, v in PRESET_INFO.items():
        p = presets.PRESETS[k]()
        out.append({"name": k, **v, "sizing": meshing.sizing(p)})
    return {"presets": out}


def _preset_case(name: str):
    fn = presets.PRESETS.get(name)
    if fn is None:
        raise HTTPException(404, f"알 수 없는 프리셋: {name}")
    p = fn()
    cs = CQC.gen_single(p) if p.domain.include_bends else None
    return p, cs


@app.get("/api/preset/{name}/step")
def preset_step(name: str):
    try:
        from fthx import cad as CAD
    except Exception as e:
        raise HTTPException(503, f"cadquery 미설치: {e}")
    p, cs = _preset_case(name)
    out = Path(tempfile.mkdtemp())
    meta = CAD.export(p, outdir=str(out), cs=cs)
    return FileResponse(meta["_files"]["step"], media_type="model/step",
                        filename=f"{p.name}.step")


def _package_bytes(p: FTHXParams, cs) -> bytes:
    """해석 패키지 zip — 서버에 아무것도 설치하지 않고 돌릴 수 있는 묶음."""
    import io as _io
    import re as _re
    import zipfile
    from fthx import cad as CAD

    out = Path(tempfile.mkdtemp())
    meta = CAD.export(p, outdir=str(out), cs=cs)
    step = Path(meta["_files"]["step"])
    bodies = _re.findall(r"PRODUCT\('([^']+)'", step.read_text(errors="ignore"))[1:]
    n = len(bodies)
    est = meshing.estimate(p, cs)

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("fthx_case/model.step", step.read_bytes())
        meta.pop("_files", None)
        z.writestr("fthx_case/case.json",
                   json.dumps(meta, indent=2, ensure_ascii=False))
        z.writestr("fthx_case/mesh.py",
                   exporters.fluent_journal(p, "model.step", "mesh.msh.h5",
                                            n_bodies=n,
                                            face_seeds=meta.get("face_seeds")))
        nc = len(cs.circuits) if cs is not None else 1
        z.writestr("fthx_case/setup.py",
                   exporters.solver_journal(p, "mesh_labeled.msh.h5",
                                            "case.cas.h5", n_circuit=nc))
        z.writestr("fthx_case/closure.json",
                   json.dumps(__import__("fthx").closure.summary(p, nc),
                              indent=2, ensure_ascii=False))
        z.writestr("fthx_case/RUN.md", exporters.run_md(p, est=est, n_bodies=n))
        z.writestr("fthx_case/settings.txt", exporters.settings_txt(p, n_bodies=n))
        z.writestr("fthx_case/bodies.txt", "\n".join(bodies))
    return buf.getvalue()


@app.post("/api/export/package")
def export_package(req: ExportIn):
    p = req.case.to_params()
    cs = req.case.to_circuits()
    data = _package_bytes(p, cs)
    out = Path(tempfile.mkdtemp()) / f"{p.name}_fluent.zip"
    out.write_bytes(data)
    return FileResponse(out, media_type="application/zip", filename=out.name)


@app.get("/api/preset/{name}/package")
def preset_package(name: str):
    p, cs = _preset_case(name)
    data = _package_bytes(p, cs)
    out = Path(tempfile.mkdtemp()) / f"{name}_fluent.zip"
    out.write_bytes(data)
    return FileResponse(out, media_type="application/zip", filename=out.name)


@app.get("/api/preset/{name}/meta")
def preset_meta(name: str):
    from fthx import cad as CAD
    p, cs = _preset_case(name)
    out = Path(tempfile.mkdtemp())
    meta = CAD.export(p, outdir=str(out), cs=cs)
    meta.pop("_files", None)
    return JSONResponse(meta)


# ══════════════════════════════════════════════════════════════════
#  정적 서빙
# ══════════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


app.mount("/web", StaticFiles(directory=str(WEB)), name="web")
