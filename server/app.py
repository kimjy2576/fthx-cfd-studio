"""
FT-HX CFD Studio — 로컬 서버

    python run.py           →  http://127.0.0.1:8020

정적 스튜디오(web/index.html)를 서빙하고, 브라우저에서 만든 형상·회로를
그대로 STEP 으로 뽑을 수 있는 API 를 제공함.
"""
from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fthx import FTHXParams, circuits as CQC, distributor as DST

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

app = FastAPI(title="FT-HX CFD Studio", version="0.4.0")


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
    return {"circuits": cs.model_dump(), **CQC.build(p, cs)}


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
#  정적 서빙
# ══════════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


app.mount("/web", StaticFiles(directory=str(WEB)), name="web")
