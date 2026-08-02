# FT-HX CFD Studio — 인수인계 핸드아웃

> 작성 시점: v0.6.0 · Fluent 경로 M1 완료 / M2 진행 중 · OpenFOAM 경로 착수 전
> 레포: **https://github.com/kimjy2576/fthx-cfd-studio** (public)

---

## 1. 이 프로젝트가 뭔지

핀-튜브 열교환기(FT-HX)의 **CFD 케이스를 사람 손 없이 생성·실행·수확하는 앱**.

설계변수를 넣으면 → 형상 → 메시 → 경계조건 → 해석 → 결과 CSV 까지
GUI 조작 없이 커맨드로 완주하는 것이 최종 상태임.

```
case.json ─▶ [GEOM] ✅ ─▶ .step ─▶ [MESH] ✅ ─▶ .msh.h5 ─▶ [LABEL] 🔶 ─▶ [SETUP] ─▶ [SOLVE] ─▶ [POST]
```

### 목표가 아닌 것

| 아님 | 이유 |
|---|---|
| 범용 CFD 자동화 도구 | 형상·물리가 무한히 변하면 자동화가 반드시 깨짐 |
| 1D 성능 예측 도구 | HX-Sim 이 담당. 중복 구현하면 반드시 갈라짐 |
| j/f 상관식 라이브러리 | 동일. HX-Sim 을 호출해 받아옴 |

### 정형화가 성립하는 근거 (프로젝트의 전제)

| 불변량 | 내용 |
|---|---|
| 위상 | 박스 + 실린더 배열 + 반토러스. 바디 클래스와 인접 관계 고정 |
| 물리 | 단상 공기(포러스) + 관벽 conjugate + 관내 냉매. 분기 없음 |
| 메시 위상 | 코어·직관은 스윕 가능, 벤드만 비정형 |

핵심은 **사이징을 파라미터의 함수로 쓸 수 있다**는 것:

```
h_air  = (Pt - Do) / N_gap           기본 (25.4-9.52)/10 = 1.588 mm
h_ref  = Di / N_d                    기본 8.22/12        = 0.685 mm
h_bend = min(h_ref, πR / N_arc)
```

정수 몇 개만 앱이 갖고 있으면 어떤 파라미터 조합에도 사이징이 자동으로 나옴.
**사람이 만질 값이 없음.**

---

## 2. 현재 상태 (v0.6.0, 테스트 96 passed)

```
fthx/params.py       형상 스키마(3층: 관배열 ⊃ 덕트 ⊃ 핀팩) · Wang 파생량(D_c 기준)
                     · 운전 조건 · HX-Sim ft_spec 상호변환
fthx/circuits.py     회로 스키마 · 생성기 4종 · 위상/간섭 검증 · 방향 반전
fthx/distributor.py  분배 솔버 · porous jump · 발달 길이 · 간섭 검사
fthx/meshing.py      사이징 유도 · y+ 판정 · 실측 보정 셀 추정 · 실현가능성 게이트
fthx/exporters.py    Fluent 저널(.py) · RUN.md · settings.txt 생성
fthx/presets.py      tutorial(관1개·8바디) / probe(관3개+벤드+케이싱·16바디)
fthx/cad.py          CadQuery/OCC → 바디 이름 승계 STEP + face_seeds
server/app.py        FastAPI (정적 서빙 · REST · git 자동 업데이트 · 패키지 zip)
web/index.html       스튜디오 — 3D · 회로 에디터 · STL · case.json · 해석 패키지
fluent/              M0 결과 · Watertight 설정 · 메시 생성기
examples/            실행 준비된 케이스 (STEP+저널 포함, 파이썬 불필요)
tests/               회귀 테스트 96개
```

### 형상 3층 구조

```
관 배열   z: 0 ~ L              ← 벤드·포트·플레넘이 붙는 곳
 └ 덕트   핀팩 + gap_y/gap_z    ← 공기 도메인 (+ 케이싱 solid)
    └ 핀 팩  L_fin, edge_y      ← 포러스 코어
```

### 검증된 수치

| 항목 | 결과 |
|---|---|
| 파생량 γ / σ / a_v / D_h (D_c 기준) | 0.9303676 / 0.5915539 / 1148.667 / 2.3469694 |
| GUI(JS) ↔ 코어(Python) | 부동소수점 일치 |
| CAD 체적 (코어·냉매·벤드) | 오차 0 |
| 회로별 유로 연결성 | 융합 후 솔리드 1개, 차이 0.00 mm³ |
| 분배 균등화 (전면 5분할) | 14.40% → 0.0000% |
| 파라미터 스윕 36조합 | 100% 무인 성공 |

---

## 3. Fluent 경로에서 배운 것 (OpenFOAM 에도 유효)

환경: **Fluent 2025 R1 (Rev 25.1.0)**, LSF 클러스터, `fluent` 은 bsub Perl 래퍼,
허용 코어 1/2/4/8/32/128/…, 서버에 pip 없음.

### 물리·형상 결론

| | 내용 |
|---|---|
| **경계층 불필요** | y+ = 190(4회로) / 131(6회로) 로 이미 벽함수 범위(30~300). 프리즘 5층은 냉매 셀을 2.8M→7M+ 로 늘리기만 함 |
| **관벽은 두께 등온** | Bi = h·t/k ≈ 6e-4. 3겹으로 나눌 이유 없음. thin volume 또는 shell |
| **포러스는 근사가 아니라 멀티스케일 분해** | 핀 실형상 = ~1e9 셀. D(주기셀)→B(풀사이즈 포러스) 로 j/f 를 넘김 |
| **케이싱이 존 분리의 열쇠** | 아래 참조 |

### 실측 셀 수

| 케이스 | 셀 | 품질 |
|---|---|---|
| tutorial (5바디, 4core) | 68,641 | 0.31 |
| probe (13바디, 32core) | 229,026 | 0.26 |
| 전체 (4열×12단) 추정 | 13.9~17.1 M | — |

⚠ **코어 수가 셀 수를 바꿈** (4core 164,461 vs 32core 229,026, +39%).
병렬 분할 경계에서 메시가 달라짐. 케이스 간 비교 시 코어 수 고정 필요.

### 값비싸게 배운 함정

1. **Proximity cells-per-gap** — 기본 3 이면 관벽(0.65mm)을 틈새로 보고 t/3 까지
   자동 세분화. 1.31M → 68.6k (19배). Min size 를 올려 막아야 함
2. **conformal 메시에서 표면 크기는 바디별로 독립이 아님** — 관 외통면과 코어
   구멍면은 같은 면. 한쪽만 조밀하게 만들면 이웃까지 폭증
3. **Fluent 은 인접 관계가 같은 면을 한 존으로 묶음** — 면적 검산으로 확인.
   `fluid_air_up-solid:1` = 18,592 = 입구 6,096 + 상하벽 6,400 + 측벽 6,096.
   → **케이싱 solid 를 두면** 측벽이 계면이 되고 자유면은 입구/출구만 남아
   자동으로 단독 존이 됨. 규칙을 이기려 하지 말고 이용할 것
4. **각도 분리(sep-face-zone-by-angle)는 쓰면 안 됨** — 존 이름을 `p-plane-N-M`
   으로 파괴하고 메시를 47MB→3.6MB 로 망가뜨림 (SIGSEGV 동반)
5. **getattr 로 TUI 경로 유무를 판정할 수 없음** — 존재하지 않는 이름에도 빈
   메뉴를 돌려줌. `dir()` 탐색은 무의미

---

## 4. OpenFOAM 경로 — 시작 지점

### "STEP까지 동일"이 아님. 거기가 갈라짐

OpenFOAM 은 B-rep 을 못 읽음. `snappyHexMesh` 는 **STL** 만 받음.

| | Fluent | OpenFOAM |
|---|---|---|
| 입력 | STEP (B-rep) | **STL** |
| 경계 이름 | STEP PRODUCT 승계 → 좌표 매칭 필요 | **STL solid 이름 = patch 이름** |
| 메시 | 형상에 맞춤 (bottom-up) | 배경 격자를 깎음 (top-down) |

**이게 오히려 유리함.** M2(좌표 라벨링)의 존재 이유가 "STEP은 면 이름을 못 싣는다"
였는데, STL 은 이름을 직접 실을 수 있어 **M2가 통째로 사라짐.**

### 새 난관 — snappyHexMesh 는 얇은 것에 약함

관벽 0.65mm, 케이싱 2mm. 배경 격자를 깎는 방식이라 셀이 폭증함.

| 안 | 관벽 처리 | 판단 |
|---|---|---|
| A | 실형상 solid | 비현실적 |
| **B** | **baffle + thermalBaffle** (두께를 물성으로) | **권고** — Bi≈6e-4 근거 |
| C | 관벽 생략 | 단순하나 정확도 손실 |

### 계획 초안

| 단계 | 내용 |
|---|---|
| **F0** | STL 내보내기 — CadQuery `exportStl`, 파일명=patch 이름, 삼각형 해상도를 곡률에서 유도. watertight·면적 검증 |
| F1 | blockMesh 배경 격자 (덕트 bbox, `h_air` 기반) |
| F2 | snappyHexMesh 딕셔너리 — refinement level, cellZone(포러스), faceZone(baffle) |
| F3 | 케이스 디렉터리 자동 생성 (`0/`, `constant/`, `system/`, `fvOptions` 포러스) |
| F4 | Allrun 스크립트 (+ LSF 제출) |
| F5 | functionObjects → CSV (기존 스키마 정렬) |

### 착수 전 확인할 것

```bash
which simpleFoam blockMesh snappyHexMesh 2>/dev/null
ls /nas/app/ | grep -i -E "openfoam|foam"
```

배포판(.org / .com / Foundation)에 따라 딕셔너리 문법과 솔버 이름이 다름.
특히 `chtMultiRegionFoam` 계열은 버전 차이가 큼.

**라이선스가 없으니 큐 없이 바로 돌 수도 있음** — 지금까지의 대기 문제가 사라질
가능성이 있음.

### 재사용 / 신규

| 재사용 그대로 | 신규 |
|---|---|
| `params.py` 형상·운전 조건 | STL 내보내기 |
| `circuits.py` 회로 전체 | blockMesh / snappy 딕셔너리 |
| `distributor.py` 분배·jump | fvOptions 포러스 |
| `meshing.py` 사이징 유도 | 케이스 디렉터리 생성 |
| `web/` 스튜디오 UI | Allrun / 후처리 |

---

## 5. 앱 사용법

### Windows

```powershell
cd fthx-cfd-studio
git pull
run.bat                 # → http://127.0.0.1:8020
```

헤더 버튼: `시험 패키지 관1개|관3개` · `해석 패키지(현재 설계)` · `앱 업데이트` ·
`회로 설계` · `STEP(서버)` · `case.json`

### Linux (Fluent 서버, 파이썬 불필요)

```bash
cd ~ && git clone https://github.com/kimjy2576/fthx-cfd-studio.git
cd fthx-cfd-studio/examples/probe
fluent 3d -meshing -g -t8 -i mesh.py
# 이후
cd ~/fthx-cfd-studio && git pull && ./examples/run.sh probe 8
cd examples/probe && ../check.sh
```

⚠ `fluent` 큐는 노드 30대 중 29대가 상시 사용 중. **한 노드 스팬 요구** 때문에
코어가 클수록 대기가 김. 작은 케이스는 1~4코어가 유리함.

---

## 6. 미해결 / 결정 필요

| # | 항목 | 상태 |
|---|---|---|
| 1 | **M2 좌표 라벨링 미완** | 냉매측은 성공(거리 0.009mm, rename OK). 공기측은 케이싱 도입 후 **미검증** — 로컬에선 자유면 1개·거리 0 확인, 클러스터 PEND 로 실행 못 함 |
| 2 | NETM 고체상 ↔ 관벽 접합 | M3 로 이월. 대안: equilibrium + UA 소스항 |
| 3 | `K_bend=0.7`, 피더 내경 4mm, span 한계 2.5×max(Pt,Pl), 스탠드오프 1.6×Do | **전부 내가 정한 기본값.** 실제 규격 확인 필요 — 분배 편차와 C2 를 직접 좌우 |
| 4 | `envelope.yaml` 강제 | M6 로 미룸 |
| 5 | 2상 확장 | 관내 1D(HX-Sim) + 헤더 CFD 하이브리드 |

---

## 7. 인접 연동

```
   case.json ──▶ FT-HX CFD Studio ──▶ STEP/STL · mesh · results.csv
        │              │ j/f 요청
        ▼              ▼
   HX-Sim (1D 세그먼트) ◀── 같은 ft_spec · 같은 회로 정의
        │
        ▼
   HPWD-DataManager (결과 수집·시각화)
```

`FTHXParams.to_ft_spec()` / `.from_ft_spec()` 로 형상 정의 공유 (구현 완료).
회로 정의 공유는 M7.

---

## 8. 작업 방식 메모 (다음 세션에)

이번 세션에서 시간을 크게 버린 패턴들:

- **로그를 보기 전에 원인을 단정함** — 30분 무응답을 "TUI 분리가 멈춤"으로
  지목했으나 실제로는 PEND 대기였음. 실행은 2분 31초였음
- **실패 신호를 한 가지로만 해석** — `run_menu` 의 `False` 를 "명령 실패"로만
  보고 "인자를 되묻는 중"일 가능성을 놓침
- **목적이 사라진 코드를 방치** — 케이싱 도입으로 각도 분리가 불필요해졌는데
  삭제하지 않아 새 실패 지점을 만듦
- **같은 방법으로 4라운드** — `dir()` 기반 TUI 탐색이 두 번째 실패에서
  무효임을 알아챘어야 했음

반대로 잘 작동한 것:

- **저널에 진단을 심어 한 번 실행으로 여러 가설을 검증** (`_try_all`, 단계별
  `>>>`/`<<<` 로그)
- **실패해도 다음 단계로 진행**시켜 왕복 횟수를 줄임
- **실측으로 추정기를 보정** (K·V/h³, 실측 2건이 추정 범위 안)
