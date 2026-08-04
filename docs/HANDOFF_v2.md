# FT-HX CFD Studio — 인수인계 핸드아웃 (v2)

> 시점: Fluent 경로 M0~M5 완료 · 열원 부과 미해결 · 주기 단위셀 착수 전
> 레포: **https://github.com/kimjy2576/fthx-cfd-studio** (public)
> 이전 핸드아웃: `docs/HANDOFF.md` (v1, OpenFOAM 착수용)

---

## 1. 지금 어디까지 왔나

```
[GEOM] ✅ ─▶ [MESH] ✅ ─▶ [LABEL] ✅ ─▶ [SETUP] 🔶 ─▶ [SOLVE] ✅ ─▶ [POST] ✅
                                          └ 포러스 열원만 미적용
```

**앱에 파라미터를 넣으면 → STEP → 메시 → 경계 라벨 → 해석 설정 → 반복 계산 →
성능 지표까지 GUI 조작 없이 완주함.**

```bash
cd ~/Desktop/dev/fthx-cfd-studio && git pull
./go.sh probe 32                    # 메시
STAGE=setup ./go.sh probe 8         # 해석 설정
ITER=500 STAGE=solve ./go.sh probe 32   # 반복 계산
cd examples/probe && ../check.sh    # 결과 + 성능 지표
```

### 검증된 것 (probe: 관3개+벤드2+케이싱, 16바디, 285k셀)

| 항목 | 결과 |
|---|---|
| 셀 존 수 = STEP 바디 수 | 16 = 16 |
| 최소 직교품질 | 0.24 |
| **공기측 ΔP** | **CFD 4.155 Pa vs closure 예측 4.157 Pa — 오차 0.06%** |
| residual | continuity 1.5e-07, energy 1.4e-10 |
| UA | 2.033 W/K (LMTD·NTU 두 방법 완전 일치) |

**ΔP 0.06% 일치가 이 프로젝트의 가장 강한 검증임.**
`closure.py` 가 j/f 상관식에서 계산한 C2 = 80.85 1/m 가 Fluent 포러스 존에
그대로 들어가 같은 물리를 재현함. 앱→저널→Fluent→물리 사슬이 닫혔다는 뜻.

---

## 2. 막힌 것 — 포러스 열원

### 증상

UA 가 2.03 W/K 인데 예측 전체 UA 는 4.03 W/K. **핀 전열이 통째로 빠져 있음.**
현재는 관벽 conduction 경로만 있고, 핀을 대표하는 체적 열원
`q = hv*(T_ref - T)`, hv = 68,826 W/m3K 가 부과되지 않음.

### 7 라운드 시도 결과

```
sources 관련 속성: ['sources']         ← 다른 경로 없음
sources.get_state()  !! TypeError: unhashable type
energy.child_names   ['1'] <-> []      ← 라운드마다 바뀜
energy['1'].set_state({'option':..})   KeyError: 'option'
nsource=1                              [--] (값 변화 없음 반환)
run_menu                               솔버에는 없음 (메싱에만 있었음)
named_expressions.create(name=..)      [OK]  ← 표현식 자체는 생성됨
```

**설정 객체의 `sources` 경로가 Fluent 2025R1 에서 불안정함.**
표현식은 만들어지는데 존에 붙이는 단계가 안 됨.

### 내가 낭비한 라운드 (반복 금지)

1. **진단을 `try/except pass` 로 감쌈** → `[스키마2]` 출력이 통째로 사라져
   두 라운드 헛돌았음. **진단은 예외를 절대 삼키지 말 것**
2. **`child_names` 가 비어 있을 때만 슬롯 확보**하도록 고침 → `get_state()`
   예외로 `have=[]` 가 되어 이미 있던 슬롯을 날림
3. **TUI 경로 추측** → `getattr` 이 없는 이름에도 빈 메뉴를 돌려주므로
   `dir()` 로 경로 유무를 판정할 수 없음. M3 에서 이미 겪었는데 반복함

---

## 3. 다음 작업 — 주기 단위셀 (Periodic Cell)

### 왜 이 방향인가

소스항으로 hv 를 넣는 것은 **j/f 상관식(반경험식)을 CFD 에 다시 집어넣는 것**임.
그러면 CFD 가 상관식을 재현할 뿐 새로 알려주는 게 없음. ΔP 는 "계수가 제대로
들어갔다"는 검증으로 값어치가 있었지만, UA 까지 그러면 도구 전체가 상관식
래퍼가 됨.

핀을 **실형상으로** 풀어 h·f 를 직접 얻으면:
- 상관식이 없는 형상(신규 루버 패턴 등)도 다룰 수 있음
- 3-mode 규약의 **on-design** 모드가 채워짐
- 소스항 문제가 우회가 아니라 **불필요**해질 수 있음 (아래 참조)

### ⚠ 단일셀만으로는 부족함

**단일셀이 주는 것은 h 라는 "숫자"이고, 지금 막힌 것은 그 값을 넣는 "통로"임.**
`closure.py` 는 이미 hv 를 계산해 두었는데 전달이 안 되고 있음.
숫자가 바뀔 뿐 통로 문제는 그대로 남음.

**따라서 단일셀 설계 시 출력 형태를 통로와 함께 정해야 함:**

| 출력 형태 | 부과 경로 | 상태 |
|---|---|---|
| h [W/m2K] → hv 소스항 | `sources.energy` | **막힘** |
| 등가 벽면 열전달계수 | 벽면 BC (`thermal`) | **동작 확인됨** |
| 유효 열전도율 k_eff | 고체 물성 | 미확인 |
| j-factor → HX-Sim | 1D 로 넘김 | CFD 불필요 |

**벽면 BC 경로는 이미 성공이 확인됨**(`thermal.temperature` [OK]).
핀을 "관벽에 붙은 확장 표면"으로 보고 등가 벽면 계수를 뽑으면
소스항 없이도 부과 가능함. 단일셀 결과를 이 형태로 뽑는 것을 우선 검토할 것.

### 규모

계획서 추정 **~1.2M 셀** (1 핀피치 × 1 관피치 × 코어 깊이).
probe(285k)의 4배지만 32코어면 감당됨. 한 번 뽑은 j/h 는 여러 풀사이즈
케이스에 재사용됨.

### 새로 만들어야 하는 것

- **핀 실형상** — 현재 `cad.py` 는 핀을 형상으로 만들지 않음(포러스 전제)
- **주기 경계** — 핀피치·관피치 방향 translational periodic
- **대칭면** — 핀 두께 중앙, 관 중심
- 그 위에 기존 메시·라벨·솔브·후처리 흐름 재사용

---

## 4. 확정된 Fluent API (2025 R1, Rev 25.1.0)

**경로는 `solver.settings.*`** — `solver.setup` 은 deprecated.

```python
S = solver.settings

# 포러스 (porous=True 로 켠 뒤에만 하위 키가 드러남)
z = S.setup.cell_zone_conditions.fluid['<zone>']
z.porous_zone.set_state({'porous': True})
z.porous_zone.set_state({'viscous_resistance': {'direction_1':.., 'direction_2':.., 'direction_3':..}})
z.porous_zone.set_state({'inertial_resistance': {'option':'constant','direction_1':..}})
z.porous_zone.set_state({'fluid_porosity': {'option':'constant','value':..}})
z.porous_zone.set_state({'relative_velocity_resistance_formulation': False})
z.general.set_state({'laminar': True})

# 경계조건
b = S.setup.boundary_conditions
b.velocity_inlet['<zone>'].momentum.set_state({'velocity_magnitude': {'option':'value','value':..}})
b.velocity_inlet['<zone>'].thermal.set_state({'temperature': {'option':'value','value':..}})
b.pressure_outlet['<zone>'].momentum.set_state({'gauge_pressure': {'option':'value','value':..}})
b.mass_flow_inlet['<zone>'].momentum.set_state({'mass_flow_rate': {'option':'value','value':..}})

# 솔버
S.solution.methods.p_v_coupling.flow_scheme = 'Coupled'
S.solution.initialization.hybrid_initialize()
S.solution.run_calculation.iterate(iter_count=N)
S.solution.report_definitions.surface / .flux   # surface_areaavg 아님
S.setup.named_expressions.create(name='..')     # 키워드 인자 필수
```

### ⚠ 반드시 지켜야 할 것

| 항목 | 이유 |
|---|---|
| `relative_velocity_resistance_formulation = False` | 기본이 True(physical velocity). 끄지 않으면 ΔP 가 1/γ² = 1.156 배 어긋남 |
| 메싱 `Cells Per Gap = 1` | 기본 3 이면 관벽(0.65mm)을 틈새로 보고 t/3 까지 세분화 → 셀 19배 |
| 존 타입 변경 | 메싱에서 이름만 바꾸면 솔버에서 전부 wall. `zone_type` 을 바꿔야 BC 를 걸 수 있음 |
| 저널 끝에 `TUI().exit()` | 솔버는 스스로 종료하지 않아 LSF 작업이 RUN 으로 남음 |
| 절대 경로로 저장 | LSF 는 작업 디렉터리를 바꿈. 상대 경로면 엉뚱한 곳에 쓰이고 이전 파일이 남아 성공처럼 보임 |
| 케이싱 solid 필수 | 없으면 상·하류 박스 자유면(입구+측벽4)이 한 덩어리가 되어 좌표 매칭 불가 |
| 바디 겹침 금지 | `cad.check_overlap()` 이 export 에서 차단. 겹치면 볼륨 메싱이 `tet initialization failed` |

---

## 5. 환경

| | |
|---|---|
| Fluent | 2025 R1 (Rev 25.1.0) |
| 스케줄러 | LSF, `fluent` 은 bsub Perl 래퍼 |
| 큐 | `fluent` — 노드 30대 중 29대 상시 사용 중 |
| 허용 코어 | 1 / 2 / 4 / 8 / 32 / 128 / 256 / 512 |
| 서버 파이썬 | **pip 없음** → Fluent 내장 파이썬 저널로 해결 |
| 후처리 | `scripts/post_standalone.py` (표준 라이브러리만) |
| 레포 위치 | `~/Desktop/dev/fthx-cfd-studio` |

**한 노드 스팬** 요구라 코어가 클수록 대기가 김. 작은 케이스는 1~8 코어가 유리.
코어당 2~5만 셀이 적정 — probe(285k)는 8~32, 전체(14M)는 128~256.

⚠ **코어 수가 셀 수를 바꿈** (4core 164,461 vs 32core 229,026, +39%).
케이스 간 비교 시 코어 수를 고정할 것.

---

## 6. 모듈 구성

```
fthx/params.py       형상 스키마(관배열 ⊃ 덕트 ⊃ 핀팩) · Wang 파생량(D_c) · 운전 조건
fthx/circuits.py     회로 생성기 4종 · 위상/간섭 검증 · 방향 반전
fthx/distributor.py  분배 솔버 · porous jump · 발달 길이
fthx/meshing.py      사이징 유도 · y+ 판정 · 실측 보정 셀 추정
fthx/closure.py      j/f → 포러스 계수 · 핀효율(Schmidt)
fthx/cad.py          CadQuery/OCC → STEP + face_seeds + 겹침 검사
fthx/exporters.py    Fluent 저널 생성 (mesh.py / setup.py)
fthx/post.py         성능 지표 (dP·Q·LMTD·UA·NTU)
fthx/presets.py      tutorial(8바디) / probe(16바디)
server/app.py        FastAPI — 스튜디오 · 패키지 zip · git 업데이트
web/index.html       3D 미리보기 · 회로 에디터 · 해석 패키지
go.sh                제출 → 대기 → 결과 → 판정 한 줄
examples/            실행 준비된 케이스 (파이썬 불필요)
tests/               회귀 테스트 120+
```

---

## 7. 작업 방식 (효과가 확인된 것)

**잘 작동함**
- 저널 각 단계를 `>>> / <<< OK|FAIL` 로 남기고 **실패해도 다음 단계로 진행** —
  한 번 실행으로 여러 가설을 검증
- **`get_state()` 로 스키마를 캐냄** — API 키를 추측하지 말 것.
  M3 에서 이 방식으로 바꾼 뒤 급격히 빨라졌음
- 예측값을 저널에 심어 CFD 결과와 **즉시 대조** (ΔP 0.06% 일치를 이렇게 확인)
- `go.sh` 로 왕복 비용 축소

**하지 말 것**
- 진단 코드를 `try/except pass` 로 감싸기
- `dir()` / `getattr` 로 TUI 경로 유무 판정
- 로그를 보기 전에 원인 단정
- 목적이 사라진 코드 방치 (케이싱 도입 후 각도분리를 안 지워 30분 낭비)

---

## 8. 미해결

| # | 항목 |
|---|---|
| 1 | **포러스 열원 부과** — `sources` 경로 불안정. 주기 단위셀 결과를 벽면 BC 형태로 뽑아 우회 검토 |
| 2 | 주기 단위셀 형상 생성 (핀 실형상 · 주기 경계 · 대칭면) |
| 3 | `K_bend=0.7`, 피더 내경 4mm, span 한계 2.5×max(Pt,Pl) — 전부 임의 기본값, 실제 규격 확인 필요 |
| 4 | NETM 고체상 ↔ 관벽 접합 미검증 |
| 5 | `envelope.yaml` 강제 (M6) |
| 6 | HX-Sim ft_spec 회로 확장 (M7) |
| 7 | 2상 확장 |
