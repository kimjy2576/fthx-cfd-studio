"""
FT-HX CAD 파라미터 스키마 (단위: mm)
HX-Sim ft_spec (Nr, Nt, Di, Do, Pt, Pl, FPI, fin_type) 과 1:1 호환.
"""
from __future__ import annotations

import math
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

MM_PER_INCH = 25.4


class TubeSpec(BaseModel):
    Do: float = Field(9.52, gt=0, description="관 외경 [mm]")
    Di: float = Field(8.22, gt=0, description="관 내경 [mm]")
    L: float = Field(500.0, gt=0, description="관 길이(스팬 방향) [mm]")
    Nr: int = Field(4, ge=1, description="열수 (공기 흐름 방향)")
    Nt: int = Field(12, ge=1, description="단수 (횡방향, 열당 관 수)")
    Pt: float = Field(25.4, gt=0, description="횡방향 피치 [mm]")
    Pl: float = Field(22.0, gt=0, description="종방향 피치 [mm]")
    layout: Literal["inline", "staggered"] = "staggered"
    k_tube: float = Field(386.0, gt=0, description="관 열전도율 [W/m-K]")

    @model_validator(mode="after")
    def _check(self):
        if self.Di >= self.Do:
            raise ValueError(f"Di({self.Di}) >= Do({self.Do})")
        if self.Pt <= self.Do:
            raise ValueError(f"Pt({self.Pt}) <= Do({self.Do}) — 횡방향 간섭")
        if self.Pl <= self.Do:
            raise ValueError(f"Pl({self.Pl}) <= Do({self.Do}) — 종방향 간섭")
        if self.layout == "staggered":
            d_diag = math.hypot(self.Pl, self.Pt / 2.0)
            if d_diag <= self.Do:
                raise ValueError(f"대각피치({d_diag:.2f}) <= Do — 엇갈림 배열 간섭")
        return self


class FinSpec(BaseModel):
    FPI: float = Field(14.0, gt=0, description="fins per inch")
    t_f: float = Field(0.115, gt=0, description="핀 두께 [mm]")
    fin_type: Literal["plain", "wavy", "louver", "slit"] = "plain"
    k_fin: float = Field(205.0, gt=0, description="핀 열전도율 [W/m-K]")

    # ── 핀 팩 치수 (관 배열과 독립) ─────────────────────────────
    # None 이면 기존 동작 그대로: 핀이 관 전장을 채우고, 높이는 반피치
    L_fin: Optional[float] = Field(None, gt=0,
        description="핀 팩 길이(z) [mm]. None → 관 길이와 동일")
    z_center: Optional[float] = Field(None,
        description="핀 팩 z 중심 [mm]. None → 관 중앙")
    edge_y: Optional[float] = Field(None, gt=0,
        description="최외곽 관 중심 ~ 핀 가장자리 [mm]. None → Pt/2")

    @property
    def Fp(self) -> float:
        """핀 피치 [mm]"""
        return MM_PER_INCH / self.FPI

    def D_collar(self, Do: float) -> float:
        """핀 칼라 외경 D_c = Do + 2·t_f.
           Wang(2000)·Chang&Wang 등 공기측 상관식은 전부 이 직경 기준으로 정의됨."""
        return Do + 2.0 * self.t_f

    @model_validator(mode="after")
    def _check(self):
        if self.t_f >= self.Fp:
            raise ValueError(f"t_f({self.t_f}) >= Fp({self.Fp:.3f}) — 핀 겹침")
        return self


class BendSpec(BaseModel):
    """리턴 벤드 규격. R_over_D 가 None 이면 반원(R = span/2) — 기존 동작."""
    R_over_D: Optional[float] = Field(None, gt=0,
        description="벤드 중심선 반경 / 관 외경. 보통 1.0~2.0")
    leg: float = Field(0.0, ge=0, description="관 끝 ~ 원호 시작 직선 다리 [mm]")

    def radius(self, span: float, Do: float) -> float:
        """실제 벤드 반경. span/2 를 넘을 수 없음(평면 U 벤드 성립 조건)."""
        if self.R_over_D is None:
            return span / 2.0
        return min(self.R_over_D * Do, span / 2.0)


class DuctSpec(BaseModel):
    """코일을 감싸는 덕트/케이싱. 핀 팩과의 간극이 곧 공기 바이패스 유로임.
       gap = 0 이면 완전 밀폐(기존 동작)."""
    gap_y: float = Field(0.0, ge=0, description="핀 가장자리 ~ 덕트 벽 (상·하 각각) [mm]")
    gap_z: float = Field(0.0, ge=0, description="핀 팩 끝 ~ 덕트 벽 (양단 각각) [mm]")

    @property
    def sealed(self) -> bool:
        return self.gap_y <= 0 and self.gap_z <= 0


class AirSide(BaseModel):
    """공기측 운전 조건 (SETUP 입력)."""
    V_face: float = Field(2.0, gt=0, description="전면 풍속 [m/s]")
    T_in: float = Field(27.0, description="입구 건구온도 [°C]")
    RH_in: float = Field(50.0, ge=0, le=100, description="입구 상대습도 [%]")
    P_in: float = Field(101325.0, gt=0, description="입구 절대압 [Pa]")


class RefSide(BaseModel):
    """냉매측 운전 조건."""
    fluid: str = "R410A"
    mode: Literal["evaporator", "condenser"] = "evaporator"
    m_total: float = Field(0.030, gt=0, description="총 질량유량 [kg/s]")
    T_sat_in: float = Field(7.0, description="입구 포화온도 [°C]")
    quality_in: Optional[float] = Field(None, ge=0, le=1,
        description="입구 건도. None → 단상(과열/과냉)으로 취급")
    superheat_out: Optional[float] = Field(5.0, ge=0, description="출구 과열도 [K]")
    subcool_out: Optional[float] = Field(None, ge=0, description="출구 과냉도 [K]")


class ThermalSpec(BaseModel):
    """열 모델 선택. SETUP 단계만 영향하고 형상·메시는 불변."""
    model: Literal["none", "equilibrium", "netm"] = "equilibrium"
    contact_R: float = Field(0.0, ge=0,
        description="핀-관 접촉 열저항 [m²K/W]. 확관 성형 접촉면")


class Operating(BaseModel):
    air: AirSide = Field(default_factory=AirSide)
    ref: RefSide = Field(default_factory=RefSide)
    thermal: ThermalSpec = Field(default_factory=ThermalSpec)


class ExportSpec(BaseModel):
    """STEP 내보내기 옵션."""
    unit: Literal["MM", "CM", "M", "INCH"] = "MM"
    precision_mode: int = Field(0, ge=-1, le=1,
        description="STEP 정밀도 0=Average, 1=Greatest, -1=Least")
    write_pcurves: bool = Field(True, description="파라메트릭 커브 기록(임포트 안정성)")


class DomainSpec(BaseModel):
    L_up: float = Field(100.0, ge=0, description="상류 연장 [mm]")
    L_down: float = Field(200.0, ge=0, description="하류 연장 [mm]")
    split_core_by_row: bool = Field(True, description="포러스 코어를 열별로 분할")
    include_tube_fluid: bool = Field(True, description="관내 냉매 체적 생성")
    include_bends: bool = Field(False, description="U-bend(리턴벤드) 생성")
    port_stub: float = Field(0.0, ge=0,
        description="냉매 입·출구 관 연장 [mm]. 경계조건을 코일에서 떼고 "
                    "유동 발달 구간을 확보함. 상류 시스템은 모델하지 않음")
    port_stub_auto: bool = Field(False, description="발달 길이만큼 자동 확보")
    port_stub_criterion: Literal["full", "practical"] = "practical"
    symmetry: Literal["none", "z"] = Field("none",
        description="z 중앙면 대칭 반쪽 모델. 공기측 스크리닝 전용 "
                    "(벤드·관내 냉매가 없어야 성립)")
    bend_gap: float = Field(8.0, ge=0, description="코어 끝면 ~ 벤드 시작 간격 [mm]")


class FTHXParams(BaseModel):
    schema_version: Literal["fthx/1"] = "fthx/1"
    name: str = "fthx_case"
    tube: TubeSpec = Field(default_factory=TubeSpec)
    fin: FinSpec = Field(default_factory=FinSpec)
    domain: DomainSpec = Field(default_factory=DomainSpec)
    duct: DuctSpec = Field(default_factory=DuctSpec)
    export: ExportSpec = Field(default_factory=ExportSpec)
    operating: Operating = Field(default_factory=Operating)
    bend: BendSpec = Field(default_factory=BendSpec)

    # ---------- 형상 배치 ----------
    def tube_centers(self) -> List[Tuple[int, int, float, float]]:
        """(row, tube, x, y) 리스트. x=공기흐름방향, y=횡방향."""
        t = self.tube
        out = []
        for r in range(t.Nr):
            x = t.Pl / 2.0 + r * t.Pl
            off = t.Pt / 2.0 if (t.layout == "staggered" and r % 2 == 1) else 0.0
            for i in range(t.Nt):
                out.append((r, i, x, t.Pt / 2.0 + i * t.Pt + off))
        return out

    @property
    def tube_z(self) -> Tuple[float, float]:
        """관 자체의 z 범위. 벤드는 여기에 붙음."""
        return 0.0, self.tube.L

    @property
    def fin_pack(self) -> dict:
        """핀 팩(= 포러스 코어 존)의 실제 범위. 관 배열과 독립."""
        t, f = self.tube, self.fin
        Lf = f.L_fin if f.L_fin is not None else t.L
        zc = f.z_center if f.z_center is not None else t.L / 2.0
        e = f.edge_y if f.edge_y is not None else t.Pt / 2.0
        ys = [c[3] for c in self.tube_centers()]
        return {"x0": 0.0, "x1": t.Nr * t.Pl,
                "y0": min(ys) - e, "y1": max(ys) + e,
                "z0": zc - Lf / 2.0, "z1": zc + Lf / 2.0,
                "L_fin": Lf, "edge_y": e, "z_center": zc}

    @property
    def core_bbox(self):
        """포러스 코어 박스 (x0,x1,y0,y1,z0,z1) — 핀 팩과 동일."""
        b = self.fin_pack
        return (b["x0"], b["x1"], b["y0"], b["y1"], b["z0"], b["z1"])

    @property
    def sym_z(self) -> Optional[float]:
        """대칭면 z 좌표. symmetry='none' 이면 None."""
        if self.domain.symmetry != "z":
            return None
        b = self.fin_pack
        return (b["z0"] + b["z1"]) / 2.0

    @property
    def duct_box(self) -> dict:
        """공기 도메인 단면. 핀 팩 + 간극."""
        b, d = self.fin_pack, self.duct
        return {"x0": b["x0"], "x1": b["x1"],
                "y0": b["y0"] - d.gap_y, "y1": b["y1"] + d.gap_y,
                "z0": b["z0"] - d.gap_z, "z1": b["z1"] + d.gap_z,
                "sealed": d.sealed}

    @model_validator(mode="after")
    def _check_fin_pack(self):
        b = self.fin_pack
        if b["L_fin"] > self.tube.L + 1e-9:
            raise ValueError(f"L_fin({b['L_fin']}) > 관 길이({self.tube.L})")
        if b["z0"] < -1e-9 or b["z1"] > self.tube.L + 1e-9:
            raise ValueError(f"핀 팩이 관 밖으로 나감: z {b['z0']:.1f}~{b['z1']:.1f} "
                             f"(관 0~{self.tube.L})")
        if b["edge_y"] <= self.tube.Do / 2:
            raise ValueError(f"edge_y({b['edge_y']}) ≤ Do/2 — 핀이 관을 못 덮음")
        if self.domain.symmetry == "z":
            bad = []
            if self.domain.include_bends:
                bad.append("리턴 벤드")
            if self.domain.include_tube_fluid:
                bad.append("관내 냉매")
            if bad:
                raise ValueError(
                    "symmetry='z' 는 공기측 스크리닝 전용임 — "
                    + ", ".join(bad) + " 가 z 대칭이 아님. 해당 옵션을 끄거나 symmetry='none'")
        dk = self.duct_box
        if dk["z0"] < -1e-9 or dk["z1"] > self.tube.L + 1e-9:
            raise ValueError(f"덕트가 관 길이를 벗어남: z {dk['z0']:.1f}~{dk['z1']:.1f} "
                             f"(관 0~{self.tube.L}). gap_z 를 줄일 것")
        return self

    # ---------- closure 입력용 파생량 (Wang 정의) ----------
    def derived(self) -> dict:
        t, f = self.tube, self.fin
        b = self.fin_pack
        W, H, L = b["x1"] - b["x0"], b["y1"] - b["y0"], b["L_fin"]   # 깊이·높이·핀팩길이
        n_tube = t.Nr * t.Nt
        N_fin = math.floor(L / f.Fp)

        Dc = f.D_collar(t.Do)                    # 공기측 특성 직경 (핀 칼라)

        A_front = H * L
        A_c = (H - t.Nt * Dc) * (L - N_fin * f.t_f)            # 최소유동면적
        A_tube_o = n_tube * math.pi * Dc * (L - N_fin * f.t_f)  # 핀 사이 노출 칼라
        A_fin = 2.0 * N_fin * (W * H - n_tube * math.pi * Dc ** 2 / 4.0)
        A_o = A_tube_o + A_fin
        sigma = A_c / A_front

        # 존 체적은 CAD 가 실제로 Do 로 잘라내므로 Do 기준을 유지해야 함
        V_box = W * H * L
        V_tube = n_tube * math.pi * t.Do ** 2 / 4.0 * L
        V_zone = V_box - V_tube
        # 핀 고체 = 플레이트(구멍 Dc) + 칼라 애뉼러스(Do→Dc, 팩 전장)
        V_fin_plate = N_fin * f.t_f * (W * H - n_tube * math.pi * Dc ** 2 / 4.0)
        V_collar = n_tube * math.pi * (Dc ** 2 - t.Do ** 2) / 4.0 * L
        V_fin_solid = V_fin_plate + V_collar

        return {
            "Fp_mm": f.Fp,
            "N_fin": N_fin,
            "L_fin_mm": L, "L_tube_mm": t.L, "edge_y_mm": b["edge_y"],
            "bare_tube_mm": t.L - L,
            "D_c_mm": Dc,
            "A_front_mm2": A_front,
            "A_min_mm2": A_c,
            "sigma": sigma,
            "A_o_mm2": A_o,
            "A_o_fin_frac": A_fin / A_o,
            "D_h_mm": 4.0 * A_c * W / A_o,
            "V_zone_mm3": V_zone,
            "porosity_gamma": 1.0 - V_fin_solid / V_zone,
            "V_fin_plate_mm3": V_fin_plate, "V_collar_mm3": V_collar,
            "a_v_1perm": (A_o / V_zone) * 1000.0,               # [1/m]
            "A_o_over_A_c": A_o / A_c,
            **self._bypass_metrics(H, L),
            "depth_mm": W, "height_mm": H, "tube_len_mm": L,
            "n_tube": n_tube,
        }

    def _bypass_metrics(self, H: float, L: float) -> dict:
        """덕트 간극(바이패스) 지표. 면적비가 작아도 저항이 훨씬 낮아
           유량 분율은 그보다 크게 나옴 — 실제 값은 CFD 가 풀어줌."""
        d, dk = self.duct, self.duct_box
        Hd, Ld = dk["y1"] - dk["y0"], dk["z1"] - dk["z0"]
        A_duct, A_core = Hd * Ld, H * L
        A_by = A_duct - A_core
        out = {"duct_H_mm": Hd, "duct_L_mm": Ld, "A_duct_mm2": A_duct,
               "A_bypass_mm2": A_by, "bypass_area_frac": A_by / A_duct,
               "sealed": dk["sealed"]}
        W = self.core_bbox[1] - self.core_bbox[0]
        if d.gap_y > 0:      # 상·하 슬롯: 폭 L, 높이 gap_y
            out["Dh_bypass_y_mm"] = 4 * (d.gap_y * L) / (2 * (d.gap_y + L))
        if d.gap_z > 0:      # 좌·우 슬롯: 폭 H, 높이 gap_z
            out["Dh_bypass_z_mm"] = 4 * (d.gap_z * H) / (2 * (d.gap_z + H))
        out["bypass_depth_mm"] = W
        return out

    # ---------- 운전 조건 파생량 ----------
    def air_props(self) -> dict:
        """습공기 물성. CoolProp 없으면 건공기 이상기체로 근사."""
        a = self.operating.air
        T = a.T_in + 273.15
        try:
            import CoolProp.CoolProp as CP
            v = CP.HAPropsSI("Vha", "T", T, "P", a.P_in, "R", a.RH_in / 100.0)
            return {"rho": 1.0 / v, "mu": CP.HAPropsSI("mu", "T", T, "P", a.P_in, "R", a.RH_in / 100.0),
                    "cp": CP.HAPropsSI("cp_ha", "T", T, "P", a.P_in, "R", a.RH_in / 100.0),
                    "W": CP.HAPropsSI("W", "T", T, "P", a.P_in, "R", a.RH_in / 100.0),
                    "source": "CoolProp/HAPropsSI"}
        except Exception:
            rho = a.P_in / (287.058 * T)
            mu = 1.458e-6 * T ** 1.5 / (T + 110.4)          # Sutherland
            return {"rho": rho, "mu": mu, "cp": 1006.0, "W": 0.0, "source": "dry-air ideal"}

    def operating_derived(self) -> dict:
        """SETUP·MESH 가 필요로 하는 운전 파생량. Wang 정의(D_c, G_max) 기준."""
        d, a = self.derived(), self.operating.air
        pr = self.air_props()
        A_front = d["A_front_mm2"] / 1e6                     # m²
        m_air = pr["rho"] * a.V_face * A_front               # kg/s
        G_max = pr["rho"] * a.V_face / d["sigma"]            # kg/m²s
        u_max = a.V_face / d["sigma"]
        Dc = d["D_c_mm"] / 1e3
        return {"air": {**pr, "A_front_m2": A_front, "m_dot_kgs": m_air,
                        "u_max_ms": u_max, "G_max": G_max,
                        "Re_Dc": G_max * Dc / pr["mu"],
                        "Re_Dh": G_max * d["D_h_mm"] / 1e3 / pr["mu"]},
                "ref": {"fluid": self.operating.ref.fluid,
                        "mode": self.operating.ref.mode,
                        "m_total_kgs": self.operating.ref.m_total,
                        "T_sat_in_C": self.operating.ref.T_sat_in},
                "thermal": self.operating.thermal.model}

    # ---------- HX-Sim 연동 ----------
    @classmethod
    def from_ft_spec(cls, ft_spec: dict, L_mm: float, name: str = "fthx_case",
                     **kw) -> "FTHXParams":
        """HX-Sim /simulate 의 ft_spec (SI, m) → CAD 파라미터 (mm)"""
        return cls(
            name=name,
            tube=TubeSpec(
                Do=ft_spec["Do"] * 1000.0, Di=ft_spec["Di"] * 1000.0, L=L_mm,
                Nr=ft_spec["Nr"], Nt=ft_spec["Nt"],
                Pt=ft_spec["Pt"] * 1000.0, Pl=ft_spec["Pl"] * 1000.0,
                layout=kw.pop("layout", "staggered"),
            ),
            fin=FinSpec(FPI=ft_spec["FPI"], fin_type=ft_spec.get("fin_type", "plain"),
                        t_f=kw.pop("t_f", 0.115)),
            domain=DomainSpec(**kw) if kw else DomainSpec(),
        )

    def to_ft_spec(self, N_seg: int = 5) -> dict:
        """CAD 파라미터 → HX-Sim ft_spec (SI, m)"""
        t, f = self.tube, self.fin
        return {"Nr": t.Nr, "Nt": t.Nt, "N_seg": N_seg,
                "Di": t.Di / 1000.0, "Do": t.Do / 1000.0,
                "Pt": t.Pt / 1000.0, "Pl": t.Pl / 1000.0,
                "FPI": f.FPI, "fin_type": f.fin_type}
