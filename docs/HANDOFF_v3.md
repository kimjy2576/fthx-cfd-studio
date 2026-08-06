# FT-HX CFD Studio — 통합 핸드아웃 (v3)

> 레포: **https://github.com/kimjy2576/fthx-cfd-studio** (public)
> 이 문서 하나로 프로젝트 전체를 인계받을 수 있게 작성함.
> 이전 문서: `docs/HANDOFF.md`(v1, OpenFOAM), `docs/HANDOFF_v2.md`(v2, M0~M5)

---

## 1. 이 프로젝트가 뭔지

핀-튜브 열교환기(FT-HX)의 **CFD 케이스를 사람 손 없이 생성·실행·수확하는 앱**.
설계변수를 넣으면 형상 → 메시 → 경계조건 → 해석 → 결과 CSV 까지 GUI 조작 없이
완주하는 것이 최종 상태임.

```
case.json ─▶ [GEOM] ─▶ .step ─▶ [MESH] ─▶ .msh ─▶ [LABEL] ─▶ [SETUP] ─▶ [SOLVE] ─▶ [POST]
```

### 목표가 아닌 것

| 아님 | 이유 |
|---|---|
| 범용 CFD 자동화 도구 | 형상·물리가 무한히 변하면 자동화가 반드시 깨짐 |
| 1D 성능 예측 도구 | HX-Sim 이 담당. 중복 구현하면 갈라짐 |
| j/f 상관식 라이브러리 | 동일. HX-Sim 을 호출해 받아옴 |

### 정형화가 성립하는 근거 (프로젝트의 전제)

| 불변량 | 내용 |
|---|---|
| 위상 | 박스 + 실린더 배열 + 반토러스. 바디 클래스와 인접 관계 고정 |
| 물리 | 단상 공기(포러스) + 관벽 conjugate + 관내 냉매. 분기 없음 |
| 메시 위상 | 코어·직관은 스윕 가능, 벤드만 비정형 |

핵심은 **사이징을 파라미터의 함수로 쓸 수 있다**는 것:

```
h_air  = (Pt - Do) / N_gap      기본 (25.4-9.52)/10 = 1.588 mm
h_ref  = Di / N_d               기본 8.22/12        = 0.685 mm
h_bend = min(h_ref, πR / N_arc)
```

정수 몇 개만 앱이 갖고 있으면 어떤 파라미터 조합에도 사이징이 자동으로 나옴.

---

## 2. 현재 상태

```
[GEOM] ✅ ─▶ [MESH] ✅ ─▶ [LABEL] ✅ ─▶ [SETUP] 🔶 ─▶ [SOLVE] ✅ ─▶ [POST] ✅
                                          └ 포러스 열원 미적용
단일셀(periodic)  형상 ✅ · 메시 ✅ · 입출구 라벨링 ❌
```

### 검증된 수치 (probe: 관3개+벤드2+케이싱, 16바디)

| 항목 | 결과 |
|---|---|
| 셀 존 수 = STEP 바디 수 | 16 = 16 |
| 셀 / 품질 | 285,051 / 0.24 |
| **공기측 ΔP** | **CFD 4.155 Pa vs closure 4.157 Pa — 오차 0.06%** |
| residual | continuity 1.5e-07 |
| UA | 2.033 W/K (LMTD·NTU 완전 일치) |

**ΔP 0.06% 일치가 이 프로젝트의 가장 강한 검증임.**
closure.py 가 j/f 상관식에서 계산한 C2 = 80.85 1/m 가 Fluent 포러스 존에
그대로 들어가 같은 물리를 재현함. 앱→저널→Fluent→물리 사슬이 닫혔다는 뜻.

### 실행 방법

```bash
cd ~/Desktop/dev/fthx-cfd-studio && git pull
./go.sh probe 32                      # 메시
STAGE=setup ./go.sh probe 8           # 해석 설정
ITER=500 STAGE=solve ./go.sh probe 32 # 반복 계산
cd examples/probe && ../check.sh      # 결과 + 성능 지표
```

케이스: `tutorial`(8바디) · `probe`(16바디) · `cell`(7바디, 단일셀)

### 로그 전달 방법 ★

파일 업로드가 반복적으로 실패함. **GitHub 이슈 #1 을 통로로 씀:**

* **이슈 본문** — 어시스턴트가 실행 명령을 씀 (매번 덮어씀)
* **첫 댓글** — 사용자가 결과를 붙여넣음
* "확인해줘" → 어시스턴트가 API 로 읽음

```bash
curl -s -H "Authorization: token $GH_TOKEN" \
  "https://api.github.com/repos/kimjy2576/fthx-cfd-studio/issues/1/comments"
```

---

## 3. 모듈 구성

```
fthx/params.py       형상 스키마(관배열 ⊃ 덕트 ⊃ 핀팩) · Wang 파생량(D_c) · 운전 조건
fthx/circuits.py     회로 생성기 4종 · 위상/간섭 검증 · 방향 반전
fthx/distributor.py  분배 솔버 · porous jump · 발달 길이 · 간섭 검사
fthx/meshing.py      사이징 유도 · y+ 판정 · 실측 보정 셀 추정 · 실현가능성
fthx/closure.py      j/f → 포러스 계수 · 핀효율(Schmidt)
fthx/cell.py         주기 단위셀 형상 (핀 실형상)
fthx/cad.py          CadQuery/OCC → STEP + face_seeds + 겹침 검사
fthx/exporters.py    Fluent 저널 생성 (mesh.py / setup.py / cell)
fthx/post.py         성능 지표 (dP·Q·LMTD·UA·NTU)
fthx/presets.py      tutorial / probe / cell
server/app.py        FastAPI — 스튜디오 · 패키지 zip · git 업데이트
web/index.html       3D · 회로 에디터 · 해석 패키지 · 단일셀 미리보기
go.sh                제출 → 대기 → 결과 → 판정 한 줄
scripts/post_standalone.py   pydantic 불필요 후처리 (서버용)
examples/            실행 준비된 케이스 (파이썬 불필요)
tests/               회귀 테스트 130+
```

### 형상 3층 구조

```
관 배열   z: 0 ~ L              ← 벤드·포트·플레넘
 └ 덕트   핀팩 + gap_y/gap_z    ← 공기 도메인 (+ 케이싱 solid)
    └ 핀 팩  L_fin, edge_y      ← 포러스 코어
```

---

## 4. 확정된 Fluent API (2025 R1, Rev 25.1.0)

**경로는 `solver.settings.*`** — `solver.setup` 은 deprecated
(Fluent 이 직접 경고: `'setup' is deprecated. Use 'settings.setup'`).

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
b.velocity_inlet['<z>'].momentum.set_state({'velocity_magnitude': {'option':'value','value':..}})
b.velocity_inlet['<z>'].thermal.set_state({'temperature': {'option':'value','value':..}})
b.pressure_outlet['<z>'].momentum.set_state({'gauge_pressure': {'option':'value','value':..}})
b.mass_flow_inlet['<z>'].momentum.set_state({'mass_flow_rate': {'option':'value','value':..}})

# 솔버
S.solution.methods.p_v_coupling.flow_scheme = 'Coupled'
S.solution.initialization.hybrid_initialize()
S.solution.run_calculation.iterate(iter_count=N)
S.solution.report_definitions.surface / .flux    # surface_areaavg 아님
S.setup.named_expressions.create(name='..')      # 키워드 인자 필수

# 메싱 (meshing 세션)
meshing.execute_tui(cmd)                          # run_menu 는 없음
mu = meshing_utilities
mu.get_face_zones(filter="*")                     # 키워드 인자만
mu.get_cell_zones(filter="*")
mu.convert_zone_ids_to_name_strings(zone_id_list=[..])
mu.get_average_bounding_box_center(face_zone_id_list=[id])
mu.get_face_zone_area(face_zone_id_list=[id])
mu.rename_face_zone(zone_name=old, new_name=new)
```

### 존 이름 규칙

```
셀 존       {바디명}-solid
외부 벽면   {바디명}-solid:1
계면        {바디A}-solid-{바디B}-solid
내부        interior--{바디명}-solid
분할된 것   {바디명}-solid-2-       (한 바디가 여러 덩이로 갈릴 때)
주기 후보   ...-shadow
```

### ⚠ 반드시 지켜야 할 것

| 항목 | 이유 |
|---|---|
| `relative_velocity_resistance_formulation = False` | 기본이 True(physical). 끄지 않으면 ΔP 가 1/γ² = 1.156 배 어긋남 |
| 메싱 `Cells Per Gap = 1` | 기본 3 이면 관벽(0.65mm)을 틈새로 보고 t/3 까지 세분화 → 셀 19배 |
| 존 타입 변경 | 메싱에서 이름만 바꾸면 솔버에서 전부 wall. `zone_type` 을 바꿔야 BC 를 걺 |
| 저널 끝에 `TUI().exit()` | 솔버는 스스로 종료 안 함 → LSF 작업이 RUN 으로 남음 |
| 절대 경로로 저장 | LSF 가 작업 디렉터리를 바꿈. 상대 경로면 엉뚱한 곳에 쓰이고 이전 파일이 남아 성공처럼 보임 |
| 케이싱 solid 필수 | 없으면 상·하류 박스 자유면(입구+측벽4)이 한 덩어리 |
| 바디 겹침 금지 | `cad.check_overlap()` 이 차단. 겹치면 `tet initialization failed` |
| 메시를 라벨링 **전에** 저장 | 라벨링이 깨져도 메시는 보존 |

---

## 5. 존재하지 않음이 확인된 API — 와 **정정** (2026-08-06)

> ⚠ **정정**: 아래 표의 "분리 불가" 계열 결론은 **조사 범위 오류**였음.
> 실측(작업 2580749·2580752)으로 뒤집힘:
>
> | 정정 | 실측 |
> |---|---|
> | 메싱 TUI `/boundary/separate/` 에 분리 명령 9종 실재 (`sep-face-zone-by-angle/seed/seed-angle/region/mark/...`) | `meshing_utilities` **서비스**만 전수조사하고 TUI 메뉴를 안 봤던 것 |
> | 각도분리는 존을 **`(id)` 리스트 문법**으로 줘야 함: `sep-face-zone-by-angle (29) 40 yes` → 존 27→31 성공 | 괄호 없는 `29 40` 은 토큰별 `Invalid entity` 로 조용히 실패 (v1 전패의 원인) |
> | 솔버 정식명은 `sep-face-zone-angle` (**"by" 없음**) — `tui.mesh.modify_zones.sep_face_zone_angle(name, 40)` 으로 wall 19→23 성공 | 아래 표의 두 실패는 전부 "by" 가 들어간 **오기** |
> | `file.write_mesh` 는 기존 파일이 있으면 overwrite 프롬프트에 걸려 **[OK] 를 돌려주고도 저장 안 함** — 저장 전 `os.remove` 필수 | 실측: write [OK] 인데 mtime 불변 |
>
> 현행: **A안 확정** — label 단계(`STAGE=label`)가 각도분리+면적판정+개명 후
> `cell_labeled.msh.h5` 저장. setup 은 라벨 확인만 하고, 없으면 B안
> (솔버 `sep_face_zone_angle`) 폴백. C안(끝단 슬래브+케이싱, eb2fcd9)은
> 오판 위에 세운 우회로였으므로 철회함.

| 시도한 것 | 결과 |
|---|---|
| `run_menu` | 메싱·솔버 **둘 다 없음** |
| `separate_face_zones_by_seed` | `meshing_utilities` 에 **없음** (getattr 이 None) — 단, TUI 메뉴에는 있음 (위 정정) |
| 좌표/seed 기반 면존 분리 | `meshing_utilities` 에 **없음**. separate 계열은 셋뿐: `separate_cell_zone_layers_by_face_zone_using_id/name`, `separate_face_zones_by_cell_neighbor` — 단, TUI 메뉴에는 있음 (위 정정) |
| `separate-face-zone-by-angle` (솔버 TUI) | `invalid command` — **명령명 오기**. 정식은 `sep-face-zone-angle` |
| `sep-face-zone-by-angle` (솔버 TUI) | `invalid command` — **명령명 오기** (동일) |
| `mesh.modify_zones.separate_face_zone_by_angle` | 속성 없음 — **속성명 오기**. 정식은 `sep_face_zone_angle` |
| 임포트 `CreateObjectPer=Face` / `OneZonePer=Face` | 둘 다 실패 — 바디 단위로만 들어옴 |
| `sources.energy` 설정 | `get_state()` 가 `TypeError: unhashable type`. 슬롯이 라운드마다 `['1']`↔`[]` |
| 각도 분리 (probe 190바디) | 존 이름을 `p-plane-N` 으로 **파괴**, 메시 47MB→3.6MB, SIGSEGV — **전역 적용**이 문제. 단일 존 대상 `(id)` 는 안전함이 실측됨 |

---

## 6. 미해결 2건

### (1) 포러스 열원 부과 — SETUP 미완

UA 가 2.03 W/K 인데 예측 전체 UA 는 4.03 W/K. **핀 전열이 통째로 빠짐.**
`q = hv*(T_ref - T)`, hv = 68,826 W/m3K 를 부과해야 하는데
`sources.energy` 경로가 불안정해 7라운드 실패.

**대안**: 벽면 BC 경로는 동작이 확인됨(`thermal.temperature` [OK]).
핀을 "관벽에 붙은 확장 표면"으로 보고 **등가 벽면 열전달계수**를 걸면
소스항 없이 부과 가능. 단일셀에서 그 형태로 값을 뽑는 것을 우선 검토할 것.

### (2) 단일셀 입출구 라벨링 — 진행 중

**형상·메시는 완료됨** (전체 피치 periodic, 7바디, 598k 셀, 품질 0.24).

문제: 입구면이 측면과 한 존으로 묶임.

```
fluid_cell_up-solid:1   면적 2.441e-3 m2
  = 입구 43.16 + 측면 2395 mm2  ← 검산 일치 (2438 vs 실측 2441)
```

`:36958` 같은 별도 존이 있으나 2.9 mm² 로 입구가 아님(잔여 면).

**A안(메싱 API 분리)·B안(솔버 TUI 분리) 모두 소진됨** — 위 5절 참조.

**남은 C안**: 상·하류 박스를 x 방향으로 얇게 한 겹 더 쪼개고, 그 슬래브의
**측면만 solid 로 감싸면** 자유면이 입구 하나만 남음. 케이싱이 대칭면이 아니라
연장부 측면에만 붙으므로 물리도 훼손되지 않음(연장부는 발달용).
probe 에서 케이싱으로 성공한 것과 같은 원리이며 **Fluent API 에 의존하지 않음.**

---

## 7. 단일셀 (주기 단위셀) 설계

핀을 **실형상**으로 풀어 j·f 를 직접 추출. 포러스를 쓰지 않으므로 (1)번 문제와 무관.

```
x  176 mm  (상류 44 + 코어 44 + 하류 88)
y  0 ~ Pt = 25.40 mm   translational periodic
z  0 ~ Fp = 1.814 mm   translational periodic, 핀이 중앙
```

**대칭 1/4 로는 안 됨** — 입구가 대칭면과 묶이고 분리 API 가 없음.
전체 피치로 가면 셀이 4배(0.38M→1.5M)지만 그 문제가 사라짐… 이라 판단했으나
**실제로는 여전히 묶임**(측면이 자유면인 것은 동일). C안이 필요한 이유.

| | 값 |
|---|---|
| Re_Dh | **489 — 층류**. 난류 모델 켜면 h 과대평가 |
| y+ | ≈ 1 |
| 메시 | 이방성 h_xy 0.25 / 간극 10층 / 핀 2층 |
| 전열면적 | 1,937 mm² |
| 관 | periodic 경계에 걸친 것은 `r01a`/`r01b` 로 분할, 합은 온전한 관과 동일 |

추출식: `cell.extract_jf(p, dp_Pa, q_W, t_out_K, area_m2)`

---

## 8. 물리 결론

| | 내용 |
|---|---|
| **경계층 불필요** (풀사이즈) | y+ = 190(4회로)/131(6회로) 로 이미 벽함수 범위. 프리즘 5층은 냉매 셀을 2.8M→7M+ 로 늘리기만 함 |
| **관벽은 두께 등온** | Bi = h·t/k ≈ 6e-4. thin volume 또는 shell |
| **포러스는 근사가 아니라 멀티스케일 분해** | 핀 실형상 = ~1e9 셀. D(주기셀)→B(풀사이즈 포러스) 로 j/f 전달 |
| **단일셀은 층류** | Re_Dh 489. 풀사이즈(Re_Dc 2089, 벽함수)와 다름 |
| 저항 분해 (probe) | 공기 0.1242 · 관벽 0.0002 · 냉매 0.1238 K/W |

### 실측 셀 수

| 케이스 | 셀 | 품질 |
|---|---|---|
| tutorial (5바디, 4core) | 68,641 | 0.31 |
| probe (13바디, 32core) | 229,026 | 0.26 |
| probe (16바디, 케이싱 포함) | 285,051 | 0.24 |
| cell (7바디, periodic) | 598,236 | 0.24 |
| 전체 (4열×12단) 추정 | 13.9~17.1 M | — |

⚠ **코어 수가 셀 수를 바꿈** (4core 164,461 vs 32core 229,026, +39%).
케이스 간 비교 시 코어 수 고정.

---

## 9. 환경

| | |
|---|---|
| Fluent | 2025 R1 (Rev 25.1.0) |
| 스케줄러 | LSF, `fluent` 은 bsub Perl 래퍼 |
| 큐 | `fluent` — 노드 30대 중 29대 상시 사용 |
| 허용 코어 | 1 / 2 / 4 / 8 / 32 / 128 / 256 / 512 |
| 서버 파이썬 | **pip 없음** → Fluent 내장 파이썬 저널로 해결 |
| 레포 위치 | `~/Desktop/dev/fthx-cfd-studio` |

**한 노드 스팬** 요구라 코어가 클수록 대기가 김. 코어당 2~5만 셀이 적정 —
probe(285k)는 8~32, 전체(14M)는 128~256. 작은 케이스는 1~8 코어가 유리.

---

## 10. 작업 방식

### 효과가 확인된 것

- 저널 각 단계를 `>>> / <<< OK|FAIL` 로 남기고 **실패해도 다음 단계로 진행** —
  한 번 실행으로 여러 가설 검증
- **`get_state()` 로 스키마를 캐냄** — API 키를 추측하지 말 것
- 예측값을 저널에 심어 CFD 결과와 **즉시 대조** (ΔP 0.06% 를 이렇게 확인)
- `go.sh` 로 왕복 비용 축소
- 형상 검증은 **눈보다 숫자** — 체적·면적·bbox 를 해석값과 대조

### 반복해서 시간을 버린 패턴 (하지 말 것)

1. **진단을 `try/except pass` 로 감쌈** → 스키마 출력이 통째로 사라져 2라운드 낭비
2. **`try_all` 이 `None`/`False` 를 성공으로 처리** → 빈 데이터가 조용히 흘러감
3. **`dir()`/`getattr` 로 API 존재 판정** → Fluent 은 없는 이름에 `None`/빈 메뉴를
   돌려줌. **`callable` 확인 필수** (`have()` 헬퍼 사용)
4. **헬퍼 정의보다 앞에서 호출** → 저널은 위→아래 실행. 단계를 앞에 끼워넣을 때
   그 단계가 쓰는 헬퍼도 함께 앞으로. (회귀 테스트로 고정됨)
5. **모듈 로드 시점에 `globals()` 평가** → `_MU()`/`TUI_EXEC()` 처럼 호출 시점 조회
6. **로그를 보기 전에 원인 단정** → 30분 무응답을 잘못 지목한 적 있음
7. **목적이 사라진 코드 방치** → 케이싱 도입 후 각도분리를 안 지워 실패 지점 생성
8. **f-string 안 `\n`/중괄호 이스케이프** → 생성된 저널이 SyntaxError.
   **저널 생성 후 `ast.parse` 검증 필수**

---

## 11. 인접 연동

```
   case.json ──▶ FT-HX CFD Studio ──▶ STEP/STL · mesh · results.csv
        │              │ j/f 요청
        ▼              ▼
   HX-Sim (1D 세그먼트) ◀── 같은 ft_spec · 같은 회로 정의
        │
        ▼
   HPWD-DataManager (결과 수집·시각화)
```

`FTHXParams.to_ft_spec()` / `.from_ft_spec()` 구현 완료. 회로 정의 공유는 M7.

---

## 12. 남은 로드맵

| # | 항목 |
|---|---|
| 1 | **단일셀 입출구 라벨링** — C안(CAD 슬래브+측면 케이싱) |
| 2 | 단일셀 solve → j·f 추출 → closure 주입 → probe ΔP 재현 검증 |
| 3 | **포러스 열원** — 등가 벽면계수 경로 |
| 4 | 루버·웨이비·슬릿 핀 형상 (현재 plain 만) |
| 5 | `envelope.yaml` 강제 (M6) · 배치 큐 |
| 6 | HX-Sim ft_spec 회로 확장 (M7) |
| 7 | 2상 확장 |
| 8 | `K_bend=0.7`, 피더 내경 4mm, span 한계 2.5×max(Pt,Pl) — 임의 기본값, 실제 규격 확인 필요 |
| 9 | NETM 고체상 ↔ 관벽 접합 미검증 |
| 10 | OpenFOAM 경로 (`docs/HANDOFF.md` 참조, 별도 세션에서 F1/F2 진행됨) |
