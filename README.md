# FT-HX CFD Studio

핀-튜브 열교환기(Fin-and-Tube HX)의 **3D 해석 전용 형상·회로 설계 도구**.

브라우저에서 설계변수를 만지고 3D로 확인한 뒤, 메시 가능한 STEP과 Fluent 존 설정
메타데이터를 한 번에 뽑는 것이 목표임. 1D 성능 예측 도구가 아니라, **CFD 케이스를
자동 생성하는 도구**임.

```
설계변수 ─┬─▶ 실시간 3D 미리보기 (Three.js)
          ├─▶ 회로 맵 에디터 + 위상/간섭 검증
          ├─▶ 분배 예측 + porous jump 계수
          └─▶ STEP (B-rep, 바디 이름 승계) + case.json
```

---

## 설계 전제

| 영역 | 처리 | 이유 |
|---|---|---|
| 공기측 핀 | **형상 생성 안 함 → 포러스** | 핀 275장을 실형상으로 만들면 메시가 감당 못 함. 블로키지는 공극률 γ로 넘김 |
| 관 내부 | **실형상 해상** | 관벽 온도분포(conjugate)와 벤드 입구 재발달이 값어치. 근사 없음 |
| 상(phase) | **단상 전용** | 2상은 분배가 quality에 지배되므로 이 모델이 성립하지 않음 |
| j/f 상관식 | **포함하지 않음** | HX-Sim이 이미 보유. 두 번 구현하면 반드시 갈라짐 |

포러스 폐합에 필요한 값(σ, γ, $a_v$, $D_h$, $A_o/A_c$)은 Wang 정의로 계산해
`case.json`에 담김.

---

## 빠른 시작

### Windows (PowerShell) — 처음 한 번

아래 블록을 통째로 복사해 붙여넣으면 됨.

```powershell
# 실행 정책 때문에 가상환경 활성화가 막히는 경우 대비 (현재 창에만 적용)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

git clone https://github.com/kimjy2576/fthx-cfd-studio.git
cd fthx-cfd-studio

py -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -U pip
pip install -r requirements.txt

python run.py
```

브라우저가 `http://127.0.0.1:8000` 으로 자동으로 열림. 종료는 `Ctrl+C`.

> `cadquery` 가 약 200MB라 첫 설치에 몇 분 걸림. 급하면 아래 최소 구성으로 먼저
> 띄워도 됨 — 스튜디오·회로 에디터·분배 예측은 전부 동작하고 STEP 생성 버튼만
> 비활성화됨.
>
> ```powershell
> pip install pydantic numpy scipy fastapi "uvicorn[standard]"
> python run.py
> ```

### Windows — 두 번째부터

```powershell
cd fthx-cfd-studio
.\.venv\Scripts\Activate.ps1
python run.py
```

### macOS / Linux

```bash
git clone https://github.com/kimjy2576/fthx-cfd-studio.git
cd fthx-cfd-studio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

### 자주 걸리는 것

| 증상 | 대응 |
|---|---|
| `Activate.ps1 ... 실행할 수 없습니다` | 위 `Set-ExecutionPolicy -Scope Process ...` 를 먼저 실행 |
| `py` 명령 없음 | `python -m venv .venv` 로 대체 (Python 3.10+ 필요) |
| `Address already in use` | `python run.py --port 8080` |
| 브라우저가 안 열림 | 주소창에 직접 `http://127.0.0.1:8000` |
| STEP 버튼 비활성 | `pip install cadquery` 후 서버 재시작. `/api/health` 로 확인 |
| 코드 수정하며 개발 | `python run.py --reload` |

### 브라우저 없이 쓰기

```bash
python scripts/gen_case.py --pattern face_split -n 4
python scripts/gen_case.py --pattern face_split -n 5 --plenum --m-total 0.03
```

### 라이브러리로 쓰기

```python
from fthx import FTHXParams, circuits as CQC, distributor as DST, cad as CAD

p  = FTHXParams()                        # 4열 × 12단, staggered, FPI 14
cs = CQC.gen_face_split(p, 4)            # 전면 4분할 (대향류)
print(CQC.build(p, cs)["ok"])            # 위상·간섭 검증

CAD.export(p, cs=cs, plenum=DST.PlenumSpec(),
           fluid=DST.Fluid("R410A", 7.0, 1.0), m_total=0.030)
```

---

## 구성

```
fthx/
  params.py        FTHXParams — 형상 스키마 + Wang 정의 파생량 + HX-Sim ft_spec 상호변환
  circuits.py      회로 스키마 · 자동 생성기 4종 · 위상 검증 · 벤드 간섭/스탠드오프
  distributor.py   병렬 회로 분배 솔버 · porous jump 계수 산정 (CoolProp 물성)
  cad.py           CadQuery/OCC → 바디 이름이 살아있는 STEP + face_seeds
server/app.py      FastAPI — 정적 서빙 + REST API
web/index.html     스튜디오 (단일 파일, 빌드 없음)
scripts/           CLI
examples/          생성 예제 (STEP + JSON)
tests/             회귀 테스트 22개
```

### 좌표계

```
x = 공기 흐름 방향 (열 r)      y = 횡방향 (단 i)      z = 관 축
```

### 바디 네이밍

Fluent Meshing이 STEP의 PRODUCT 이름을 존 이름으로 승계함.

| 이름 | 존 |
|---|---|
| `fluid_air_up` / `fluid_air_core_rNN` / `fluid_air_down` | 공기 (코어는 porous) |
| `solid_tube_rNNtMM` | 관 벽 (solid) |
| `fluid_ref_rNNtMM` | 관내 냉매 |
| `solid_bend_cNN_kMM` / `fluid_bend_cNN_kMM` | 리턴 벤드 |
| `fluid_plenum_in_z0` / `fluid_plenum_out_z1` | 분배기 / 헤더 |
| `fluid_feed_cNN_in_a` / `_b` | 피더 (둘 사이 면이 porous jump) |

STEP은 **면** 이름을 싣지 못하므로, 경계 지정은 `case.json`의 `face_seeds`
좌표로 면을 집는 방식을 씀 (`air_inlet`, `ref_inlet_cNN`, `porous_jump_cNN` 등).

---

## 회로 설계

관 ID는 `tid = r * Nt + i`. **입구 끝단만 정하면 이후 벤드 끝단은 자동 교대**함
(k 홀수 → z1, 짝수 → z0).

### 자동 생성기

| 패턴 | 회로 수 | 특징 |
|---|---|---|
| `single` | 1 | 소형 코일 |
| `row_serpentine` | Nr | 회로마다 한 열만 지남 |
| `face_split` | N | 모든 열을 지나는 대향류. **기본 권장** |
| `interlaced` | N | 공기 성층을 고르게 겪음. 단 구조적 교차 발생 |

### 검증

- **위상** — 중복·미배정·범위 초과·재방문·span 한계·`m_frac` 합
- **간섭** — 벤드를 스텁+호+스텁 폴리라인으로 이산화해 3D 최소거리 검사.
  z로 밀어 해소되는 **근접**과, 아무리 밀어도 남는 **구조적 교차**를 구분함

교차는 한 벤드의 호가 다른 벤드가 쓰는 관 위를 지날 때 생김. 바깥 벤드의 직선
스텁이 안쪽 호를 반드시 관통하므로 z 이동으로는 못 풂 → 회로를 바꾸거나 꺾인(jogged)
벤드가 필요함. 실제 인터레이스드 코일의 제작 난이도가 여기서 나옴.

동심 네스팅(0→5, 1→4, 2→3)은 제작 가능하므로 통과시킴.

---

## 다중 입출구

회로가 C개면 냉매 입구도 C개가 됨. 회로별로 mass-flow-inlet을 따로 주면 *분배를
알고 싶은데 분배를 입력해야 하는* 모순이 생김.

**입구 플레넘 하나로 묶고 총유량만 주면, 분배는 유로 저항 차이로 풀림.**
경계조건은 `ref_inlet_main_z0`(총유량)과 `ref_outlet_main_z1`(압력) 둘뿐임.

회로 간 불균형이 남으면 피더의 porous jump로 균등화함:

$$\Delta p_{jump} = C_2 \cdot \tfrac{1}{2}\rho v^2 \cdot \Delta m
\quad\Rightarrow\quad C_2 = \frac{2\,\Delta p_{jump}}{\rho v^2 \Delta m}$$

전면 5분할 예제(Nt=12를 5로 나누면 밴드가 2·3·2·3·2로 불균등):

```
분배 편차 14.40%  →  0.0000%      C2 = [450.4, 0, 450.4, 0, 450.4] 1/m
```

> ⚠ 단상 한정. 2상에서는 분배가 압력강하가 아니라 입구 quality와 관성 분리에
> 지배되므로 이 접근이 성립하지 않음. 그때는 분배기·피더를 실형상으로 풀거나
> 1D 세그먼트 모델로 넘겨야 함.

---

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 스튜디오 |
| GET | `/api/health` | cadquery·CoolProp 설치 여부 |
| POST | `/api/circuits/generate` | 패턴 자동 생성 + 검증 |
| POST | `/api/circuits/validate` | 사용자 회로 검증 |
| POST | `/api/distribution` | 분배 예측 + jump 계수 |
| POST | `/api/export/step` | STEP 파일 |
| POST | `/api/export/meta` | case.json (형상·회로·존·face_seeds) |

---

## 검증 상태

`pytest -q` → **22 passed**

| 항목 | 결과 |
|---|---|
| 코어 존 체적 (CAD vs 해석식) | 오차 0 |
| 냉매 체적 (직관·벤드) | 오차 0 |
| 회로별 유로 연결성 | 관+벤드 융합 후 **솔리드 1개**, 체적 차이 0.00 mm³ |
| 플레넘→피더→회로 연결성 | 솔리드 1개 |
| STEP 바디 이름 승계 | PRODUCT 이름 확인 |
| 분배 균등화 | 14.40% → 0.0000%, 총유량 보존 |
| 파라미터 스윕 36조합 | 100% 무인 성공 |
| GUI(JS) ↔ 코어(Python) 파생량 | 부동소수점 일치 |

---

## HX-Sim 연동

`FTHXParams.to_ft_spec()` / `.from_ft_spec()` 로 1D 세그먼트 모델과 같은 형상
정의를 공유함. 회로 맵 하나로 1D와 CFD를 동시에 돌리는 것이 목표.

```python
p.to_ft_spec()
# {'Nr': 4, 'Nt': 12, 'N_seg': 5, 'Di': 0.00822, 'Do': 0.00952,
#  'Pt': 0.0254, 'Pl': 0.022, 'FPI': 14.0, 'fin_type': 'plain'}
```

---

## 로드맵

- [x] 형상 파라미터 스키마 + STEP 생성
- [x] 스튜디오 (3D 미리보기 · STL · case.json)
- [x] 냉매 도메인
- [x] 회로 스키마 · 검증 · 자동 생성기
- [x] 회로 맵 에디터
- [x] 일반화 벤드 · 회로별 입출구
- [x] 플레넘 · porous jump · 분배 예측
- [ ] HX-Sim `ft_spec` 회로 확장
- [ ] Fluent Meshing 저널 자동 생성 (`face_seeds` 기반 경계 라벨링)
- [ ] 핀 periodic 셀 해석 → j/f (`closure/on_design`)
- [ ] 2상 확장 (관내 1D 세그먼트 + 헤더 CFD 하이브리드)

## 알려진 제약

- **STL은 미리보기용.** 삼각형 근사라 곡률 사이징과 경계층이 무너짐. 해석 입력은 STEP.
- 스튜디오 3D의 핀은 **표시 전용**. 내보내는 도메인에는 없음.
- 벤드 곡률 추가손실 `K_bend=0.7`, 피더 내경 4mm은 **기본값**. 실제 규격에 맞춰
  조정해야 분배 편차와 C2가 맞음.
- Fluent 포러스 존의 *Superficial / Physical Velocity* 설정을 틀리면 ΔP가
  $1/\gamma^2$배 어긋남. 압도적 1위 오류원.
- 바디 간 계면은 Share Topology를 **All**로 두지 않으면 포러스↔관벽이 conformal로
  붙지 않음.

## 라이선스

MIT
