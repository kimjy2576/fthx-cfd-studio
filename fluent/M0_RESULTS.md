# M0 스모크 테스트 결과 (Fluent 2025 R1, Rev 25.1.0)

두 케이스 모두 Watertight Geometry 워크플로우로 볼륨 메시까지 완주함.
설정은 [`WATERTIGHT.md`](WATERTIGHT.md).

## 결과

| | tutorial (관1개) | probe (관3개+벤드2) |
|---|---|---|
| 바디 / 셀 존 | 5 / 5 | 13 / 13 |
| 표면 face | 26,050 | — |
| 총 셀 | 68,641 | **164,461** |
| 최소 직교품질 | 0.31 | **0.225** |
| 소요 | 0.09 분 | 0.21 분 (4 core) |

## 확정된 것

**존 이름 규칙**

```
셀 존       {바디명}-solid
외부 벽면   {바디명}-solid:1
계면        {바디A}-solid-{바디B}-solid
내부        interior--{바디명}-solid
```

바디 이름이 그대로 승계됨. `-solid` 는 재질이 아니라 CAD 바디를 부르는 이름.

**Share Topology 동작** — `fluid_air_core_r01-solid-fluid_air_up-solid` 같은
계면 존이 생성됨. imprint 도 동작함(probe 는 핀팩 80mm < 관 100mm).

## 발견 (전부 M1 설계에 반영해야 함)

### 1. 계면 존 이름을 신뢰할 수 없음

코어↔상하류는 `A-solid-B-solid` 로 나오지만, 관벽↔코어/냉매는 별도 이름 없이
각각 코어·냉매 존에 흡수됨. 면적 역산으로 확인:

| 존 | faces | 실제 내용 |
|---|---|---|
| `fluid_air_core_r01-solid:1` | 3899 | 코어 외벽 + **관 외통면 2,991 mm²** |
| `fluid_ref_r01t01-solid:1` | 2495 | **관 내통면 2,582 mm²** |
| `solid_tube_r01t01-solid:1` | 180 | 관 양끝 고리면만 (36 mm²) |

→ **`face_seeds` 좌표 기반 라벨링이 필수.** 이름 규칙 의존은 불가.

### 2. Proximity 가 셀 수를 지배함

Fluent 의 Proximity 기본값이 '틈새당 셀 3개'. 관벽(0.65mm)을 틈새로 인식해
자동으로 t/3 = 0.217mm 까지 세분화함. 실측 **1,308,281 셀** →
`Min 0.685 / Cells Per Gap 1` 로 **68,641 셀** (19배 감소).

Local Sizing 을 지워도 그대로였던 것이 단서였음 — Fluent 가 알아서 만들고 있었음.

### 3. 관벽이 품질 병목

probe 최저 품질이 벤드가 아니라 관벽임 (`solid_tube_r01t02` 0.225).
두께 0.65mm 에 셀 0.73mm → 1겹, poly 가 눌려 납작해짐.

→ **Thin Volume Mesh 로 두께 방향 스윕**하면 육면체/프리즘이 되어 품질이
크게 오름. Bi ≈ 6e-4 라 1층이면 충분(두께 방향 등온).

## 실측 셀밀도 → 전체 케이스 외삽

| 존 | 밀도 [1/mm³] | 등가 크기 |
|---|---|---|
| core (포러스) | 0.4344 | 1.32 mm |
| ref | 2.2113 | 0.77 mm |
| wall | 2.6460 | 0.72 mm |
| bend (유체/솔리드) | 2.87 / 3.03 | 0.70 / 0.69 mm |
| up / down | 0.0768 / 0.0590 | 2.35 / 2.57 mm |

**전체 케이스(4열×12단, 전면 4분할, 상류 100 / 하류 200mm) ≈ 12.8 M 셀**

| 존 | 셀 | 비중 |
|---|---|---|
| core | 5.33 M | 34.8% |
| ref | 2.82 M | 18.4% |
| wall | 1.15 M | 7.5% |
| bend | 0.37 M | 2.3% |
| **up + down** | **3.09 M** | **24.2%** |

상·하류 연장이 1/4 을 차지함 — 유동 발달 외에는 정보가 없는 영역이므로
Max size 를 더 키우거나 하류 길이를 줄일 여지가 있음 (C 단계 항목).


---

# M1 결과 — 저널 자동 실행 (LSF 배치)

`fluent 3d -meshing -g -t32 -i mesh.py` 로 **GUI 조작 없이 완주**함.

| 단계 | 결과 |
|---|---|
| InitializeWorkflow ~ 7. Volume Mesh | 전부 OK |
| 8. check-mesh / 9. boundary list | OK |
| 10. write mesh | **OK** → `mesh.msh.h5` 생성 |

| | 값 |
|---|---|
| 셀 존 | **13** (STEP 바디 수와 일치) |
| 셀 | **229,026** |
| 최소 직교품질 | **0.26** |
| 소요 | 0.18 분 (32 core) |

## 확정된 것

**워크플로우 인자 이름이 전부 맞았음** — 녹화 없이 문서 기준으로 작성한 값이
2025 R1 에서 그대로 통했음:

```python
{"CFDSurfaceMeshControls": {"MinSize", "MaxSize", "GrowthRate",
                            "CellsPerGap", "SizeFunctions", "ScopeProximityTo"}}
{"SetupType": "The geometry consists of both fluid and solid regions and/or voids",
 "InvokeShareTopology": "Yes", ...}
{"VolumeFill": "polyhedra"}
```

## 발견

### `tui` 는 전역이 아님

Fluent 내장 파이썬에서 `tui.mesh.check_mesh()` 가 `NameError`.
1차 실행에서 8~10 단계가 실패했고, **10 단계가 메시 저장이라 파일이 안 만들어졌음.**
→ `TUI()` 헬퍼로 여러 후보를 탐색하도록 수정해 해결.

### 코어 수가 셀 수를 바꿈

| | 셀 |
|---|---|
| GUI, 4 core | 164,461 |
| 배치, 32 core | **229,026** (+39%) |

병렬 분할 경계에서 메시가 달라지기 때문임.
**케이스 간 비교 시 `-t` 를 고정해야 함.** 같은 코어 수에서는 재현됨
(32 core 두 번 실행 모두 229,026).

## 환경

| | |
|---|---|
| 스케줄러 | LSF (`fluent` 은 bsub Perl 래퍼) |
| 큐 | `fluent` |
| 허용 코어 | 1 / 2 / 4 / 8 / 32 / 128 / 256 / 512 |
| Fluent | 2025 R1 (Rev 25.1.0) |
| 서버 파이썬 | pip 없음 → **Fluent 내장 파이썬 저널로 해결** |


---

# M2 진행 — 좌표 기반 경계 라벨링

## 확정된 API (2025 R1)

```python
mu.get_face_zones(filter="*")                              # -> [id, ...]  41개
mu.get_cell_zones(filter="*")                              # -> [id, ...]  13개
mu.convert_zone_ids_to_name_strings(zone_id_list=ids)      # -> [name, ...]
mu.get_average_bounding_box_center(face_zone_id_list=[id]) # -> [x, y, z]
mu.get_face_zone_area(face_zone_id_list=[id])              # -> float
mu.rename_face_zone(zone_name=old, new_name=new)           # -> True
```

**키워드 인자만 허용.** 위치 인자는 `TypeError: Only keyword arguments should be provided`.

## 성공한 부분

```
ref_inlet_c01   -> fluid_ref_r01t01-solid:1   거리 0.009 mm   rename OK
ref_outlet_c01  -> fluid_ref_r01t03-solid:1   거리 0.010 mm   rename OK
```

**좌표 매칭 방식이 검증됨.** 계면 이름을 신뢰할 수 없다는 M0 결론에 대한 해답이 맞음.

## 존 그룹핑 규칙 (핵심 발견)

Fluent 은 **인접 관계가 같은 면을 한 존으로 묶음.** 면적 검산으로 확인:

`fluid_air_up-solid:1` = 18,592 mm²
= 입구면(76.2×80=6,096) + 상하벽(2×40×80=6,400) + 측벽(2×40×76.2=6,096)

| | 결과 |
|---|---|
| 관 끝면 (52.1 mm²) | 이웃 없음 → **단독 존** → 매칭 성공 |
| 박스 외벽 5면 | 전부 이웃 없음 → **한 덩어리** → 입구면 특정 불가 |

→ 박스 외벽은 **기하학적 분리(각도)** 가 필요함.

## 미해결

`boundary.manage.separate` 는 존재하지 않음 (`AttributeError`).
분리 명령의 정확한 TUI 경로를 탐색 중 (13a 단계).

대안: 솔버의 `/mesh/modify-zones/separate-face-zone-by-angle` 는 오래된 안정
명령이고, M3(SETUP)가 어차피 솔버에서 도므로 거기서 라벨링해도 됨.


---

# M2 완료 (2025 R1, 32 core)

케이싱 solid 도입으로 **좌표 기반 경계 라벨링이 성립함.**

```
air_inlet       -> fluid_air_up-solid:1      거리 0.000 mm
air_outlet      -> fluid_air_down-solid:1    거리 0.000 mm
ref_inlet_c01   -> fluid_ref_r01t01-solid:1  거리 0.004 mm
ref_outlet_c01  -> fluid_ref_r01t03-solid:1  거리 0.010 mm
```

| | 값 |
|---|---|
| 셀 존 | 16 (= STEP 바디 수) |
| 셀 | 285,051 |
| 최소 직교품질 | 0.24 |
| 소요 | 0.15 분 |
| 메시 파일 | mesh.msh.h5 / mesh_labeled.msh.h5 각 59.9 MB |

## 이르기까지 겪은 것

1. **각도 분리(sep-face-zone-by-angle)** — 존 이름을 `p-plane-N-M` 으로 파괴하고
   메시를 47MB→3.6MB 로 망가뜨림(SIGSEGV 동반). 쓰면 안 됨
2. **케이싱이 관을 관통** — 코어 케이싱이 핀 팩만 덮는데 관은 그 밖까지 나가
   체적이 겹침(6쌍). 볼륨 메싱이 `tet initialization failed` 로 실패.
   표면 메시는 통과하므로 늦게 발견됨 → `cad.check_overlap()` 으로 CAD 단계에서 차단
3. **케이싱에서 관·냉매·벤드를 cut** 하여 해결

## 확정

`face_seeds` 는 4개면 충분함 — 덕트 벽은 케이싱과의 계면이 되어 별도 이름이
불필요. 케이싱이 없으면 상·하류 박스 자유면(입구+측벽4)이 한 덩어리가 되어
좌표 매칭이 성립하지 않으므로 **케이싱 사용이 사실상 필수**임.


## 저장 경로 주의

LSF 로 제출되면 작업 디렉터리가 바뀔 수 있음. 상대 경로로 저장하면 엉뚱한 곳에
쓰이고, 폴더에 이전 실행 파일이 남아 있으면 성공한 것처럼 보임.
→ 저널이 **자기 파일 위치(`_HERE`) 기준 절대 경로**를 쓰도록 함.
→ `17. 저장 파일 확인` 이 경로·크기·시각을 직접 출력해 확정할 수 있게 함.

## M2 최종 (2026-08-03, 32 core, 깨끗한 clone)

```
17 단계 전부 OK · 셀 존 16 · 셀 285,051 · 품질 0.24
mesh.msh.h5 / mesh_labeled.msh.h5  각 59.9 MB

air_inlet       -> fluid_air_up-solid:1      0.000 mm
air_outlet      -> fluid_air_down-solid:1    0.000 mm
ref_inlet_c01   -> fluid_ref_r01t01-solid:1  0.004 mm
ref_outlet_c01  -> fluid_ref_r01t03-solid:1  0.010 mm
임계값 1mm 초과: 없음
```


---

# M3 완료 — SETUP (2025 R1)

`fluent 3ddp -g -t8 -i setup.py` 로 GUI 조작 없이 완주.
13단계 전부 OK, 실패 0, `case.cas.h5` 54.2 MB 저장.

## 최종 포러스 상태 (실측)

```
porous  = True
gamma   = {'option':'constant', 'value': 0.930063}
1/alpha = {'direction_1/2/3': 5123399.9}   1/m2
C2      = {'option':'constant', 'direction_1/2/3': 80.8536}   1/m
relative_velocity_resistance_formulation = False    ← superficial
Laminar Zone = True
```

경계조건: 공기 2 m/s / 300.15 K (I=5%, D_h 2.299mm) · 0 Pa gauge
          냉매 0.03 kg/s / 280.15 K

## 확정된 API (Fluent 2025 R1)

**경로는 `solver.settings.*`** — `solver.setup` 은 deprecated
(Fluent 이 직접 경고: `'setup' is deprecated. Use 'settings.setup' instead`).

```python
S = solver.settings
S.setup.cell_zone_conditions.fluid['<zone>']
    .porous_zone.set_state({'porous': True})          # 먼저 켜야 하위 키가 드러남
    .porous_zone.set_state({'viscous_resistance': {'direction_1':.., 'direction_2':.., 'direction_3':..}})
    .porous_zone.set_state({'inertial_resistance': {'option':'constant','direction_1':..}})
    .porous_zone.set_state({'fluid_porosity': {'option':'constant','value':..}})
    .porous_zone.set_state({'relative_velocity_resistance_formulation': False})
    .general.set_state({'laminar': True})

S.setup.boundary_conditions.velocity_inlet['<zone>']
    .momentum.set_state({'velocity_magnitude': {'option':'value','value':..}})
    .thermal.set_state({'temperature': {'option':'value','value':..}})
    .turbulence.set_state({'turbulent_specification': 'Intensity and Hydraulic Diameter',
                           'turbulent_intensity': 0.05, 'hydraulic_diameter': ..})

S.solution.methods.p_v_coupling.flow_scheme = 'Coupled'
S.solution.initialization.hybrid_initialize()
```

## 겪은 것 (5 라운드)

오류가 매 라운드 한 단계씩 앞으로 감:

| 라운드 | 실패 | 원인 |
|---|---|---|
| 1 | `'TUIMenu' object has no attribute 'velocity_inlet'` | TUI 경로 추측. getattr 이 빈 메뉴를 돌려주므로 판정 불가 |
| 2 | `porous` 속성 없음 | `solver.setup` 이 deprecated |
| 3 | `'velocity_inlet' has no attribute 'air_inlet'` | 존이 전부 wall — 이름만 바꾸고 **타입을 안 바꿈** |
| 4 | `KeyError: 't'` / `'porous'` | 키 이름 (`temperature`, `porous_zone.porous`) |
| 5 | 저항 키 | `porous=True` 로 켠 뒤에만 드러남 |

**교훈: 추측하지 말고 `get_state()` 로 스키마를 캐낼 것.**
4라운드부터 그 방식으로 바꾼 뒤 급격히 빨라졌음.

## ⚠ relative_velocity_resistance_formulation

**기본값이 True (= physical velocity).** superficial 기준으로 산출한 C2 를
쓰려면 반드시 False 로 꺼야 함. 켜두면 dP 가 1/gamma^2 = 1.156 배 어긋남.
계획 단계에서 '압도적 1위 오류원' 으로 지목했던 항목이 실제로 켜져 있었음.


---

# M4 1차 — 반복 계산 성립 (2025 R1, 32 core)

`ITER=50 STAGE=solve` 로 반복이 실제로 돌았음.

```
12. 반복 50 회
    [OK] settings run_calculation.iterate
```

## 물리 검증 — closure 예측과 일치

| | 값 |
|---|---|
| 공기 입구 압력 | 4.0985 Pa |
| 공기 출구 압력 | -0.0011 Pa |
| **CFD 코어 dP** | **4.10 Pa** |
| **closure 예측** | **4.16 Pa** |
| **오차** | **1.4%** |

포러스 계수가 제대로 들어갔다는 직접 증거임.
`relative_velocity_resistance_formulation` 을 끄지 않았다면
1/gamma^2 = 1.156 배, 즉 15.6% 어긋났을 값임.

공기 출구온도 297.53 K (입구 300.15 K) — 냉매(280.15 K)로 열이 빠져나감.
방향과 크기 모두 타당함.

## 확정 API

```python
S.solution.run_calculation.iterate(iter_count=N)
```

반복 횟수는 `FTHX_ITER` 환경변수로 주입.

## 미확정

`report_definitions` 하위에 `surface_areaavg` / `surface_massavg` / `flux` 가
없음. 면적분 직접 계산(`report.surface_integrals.*`)은 동작하므로 물리량은
얻을 수 있으나, 수렴 감시용 리포트는 타입 이름 확정이 필요함.

50회는 초기 과도구간이라 수렴 판정은 아직임.

---

# M4 완료 — 수렴 (500회, 32 core)

| | 값 |
|---|---|
| 공기 입구 | 4.1519 Pa |
| 공기 출구 | -0.0032 Pa |
| **CFD 코어 dP** | **4.155 Pa** |
| **closure 예측** | **4.156 Pa** |
| **오차** | **0.03%** |

residual: continuity 1.5e-07, energy 1.4e-10 — 사실상 기계 정밀도.
50회 4.10 → 500회 4.155 로 수렴.

**closure(j/f 상관식) → C2 80.85 1/m → Fluent 포러스 → CFD dP** 사슬이
소수점 셋째 자리까지 일치함. 앱이 계산한 계수가 그대로 물리로 재현됨.

## 확정 API

```python
S.solution.run_calculation.iterate(iter_count=N)
S.solution.report_definitions.surface   # surface_areaavg 아님
S.solution.report_definitions.flux
# 하위 전체: surface, flux, force, volume, moment, aeromechanics,
#            drag, lift, expression, single_val_expression, user_defined ...
```

## 잡은 버그

`try_all` 이 성공 후에도 다음 후보를 실행해 **iterate 가 두 번 돌았음**
(500 요청인데 1155회까지 진행). 결과에는 무해했으나 조기 반환하도록 수정.
