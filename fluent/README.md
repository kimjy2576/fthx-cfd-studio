# Fluent 연동 — M0 스모크 테스트

STEP 이 Fluent Meshing 에 깨끗히 들어오는지 확인하는 단계임.
여기서 문제가 있으면 메시 생성기(M1)를 다 만들고 되돌아와야 하므로 **가장 값싼
위험 제거**임.

> **SpaceClaim / Discovery 는 Windows 전용임.** Linux 에는 없으므로
> Fluent Meshing 으로 확인함. 어차피 최종 소비자가 Fluent Meshing 이라
> 그쪽이 읽는 모습이 기준임.

---

## 0) 시험용 STEP 만들기

### 작은 케이스 먼저 (권장)

전체 케이스(190 바디)로 첫 메시를 돌리면 오래 걸리고 실패 시 원인 분리가
어려움. 구조적으로 확인할 것은 전부 들어 있으면서 1~2분에 끝나는 크기:

```bash
python scripts/gen_probe.py
# → out/probe_small.step   (13 바디, 85 KB)
#    1열 x 3단, 관 100mm, 핀팩 80mm, 단일 회로(벤드 2개)
```

바디 13개:

```
fluid_air_up  fluid_air_core_r01  fluid_air_down
solid_tube_r01t01..03   fluid_ref_r01t01..03
solid_bend_c01_k01..02  fluid_bend_c01_k01..02
```

### 전체 케이스



```bash
python scripts/gen_case.py --pattern face_split -n 4
# → out/fthx_face_split_4.step  (바디 190개)
```

임포트가 느리면 파일을 가볍게 (2.30 → 1.26 MB):

```python
from fthx import FTHXParams, circuits as CQC, cad as CAD
p = FTHXParams(name="probe", export={"write_pcurves": False})
CAD.export(p, cs=CQC.gen_face_split(p, 4))
```

---

## 방법 A — GUI (가장 확실, 5분)

설정 순서 전체는 [`WATERTIGHT.md`](WATERTIGHT.md) 참고.

Linux 서버에 X11 포워딩이나 VNC 가 되면 이게 제일 빠름. 버전 차이에 안 걸림.

```bash
fluent 3d -meshing
```

1. **File → Import → CAD…**
2. 파일 선택, **Length Unit = mm**
3. **Create Object Per** = `Face`  ← 좌표 기반 라벨링에 필요함
4. **Import**

확인할 것:

| | 기대값 |
|---|---|
| Outline 트리의 오브젝트 수 | **190** (전면 4분할, 루트 제외) |
| 이름 승계 | `fluid_air_core_r01`, `solid_tube_r01t01`, `fluid_bend_c01_k01` … |
| 형상 | 4열 × 12단 코일 + 리턴 벤드 + 상·하류 박스 |
| 콘솔 경고 | 없어야 함 (있으면 전문 복사) |

이어서 **Describe Geometry → Share Topology = All** 을 적용하고,
`fluid_air_core_r01` 과 `solid_tube_r01t01` 이 conformal 로 붙는지 확인.
(우리 CAD 는 두 바디가 14,954 mm² 원통면을 정확히 공유하도록 만들어져 있음)

---

## 방법 B — 스크립트 (헤드리스)

```bash
pip install ansys-fluent-core
python fluent/smoke_import.py out/fthx_face_split_4.step --cores 8
```

Fluent 버전마다 PyFluent API 이름이 달라지므로, 이 스크립트는 여러 경로를
순서대로 시도하고 **어느 것이 동작했는지** 로그에 남김. 전부 실패해도 사용
가능한 API 와 오류를 덤프하므로 그 출력으로 버전 고정이 가능함.

출력 끝에 `*.fluent-probe.json` 이 저장됨.

---

## 보내줄 것

1. 오브젝트 수 (190 과 일치하는지)
2. 면 존 이름 몇 개 — **per-face granularity 에서 어떤 형식인지가 핵심**
   (`fluid_air_up:1` / `wall-fluid-air-up` / … 버전마다 다름)
3. 경고·오류 전문
4. `fluent --version` 출력과 OS

이 네 개가 있으면 M1(메시 저널 생성기)과 M2(좌표 기반 라벨링)를 실측 기반으로
설계할 수 있음.

---

# M1 — 메시 생성기

```bash
pip install ansys-fluent-core
python -m fluent.mesh out/probe_small.step --preset probe --cores 8
```

`fthx.meshing.sizing()` 이 유도한 값을 Watertight 워크플로우에 그대로 주입함.
사람이 만질 값이 없음. M0 실측으로 확정한 기본값이 들어가 있음:

| | 값 | 근거 |
|---|---|---|
| Cells Per Gap | 1 | 기본 3 이면 관벽을 틈새로 보고 t/3 세분화 (1.31M → 68.6k) |
| Share Topology | Yes | 바디 간 conformal 접합 |
| 경계층 | 없음 | y+ 190/131 로 이미 벽함수 범위 |
| Fill | polyhedra | |

## 품질 게이트

| 항목 | 기준 | 실패 의미 |
|---|---|---|
| 셀 존 수 = STEP 바디 수 | 일치 | 임포트 또는 Share Topology 실패 |
| 최소 직교품질 | > 0.10 | 메시 품질 미달 |
| 셀 수 | < 예산 (기본 20M) | 배치 불가 |

## 재시도 사다리

셀 존 불일치나 품질 미달이면 단계적으로 세분화하며 재시도함.
**예산 초과는 세분화로 나아지지 않으므로 즉시 중단**함.

```
1. 기본                     Min 0.685 / Max 3.176
2. 코어 세분  N_gap 14       Min 0.685 / Max 2.269
3. 전반 세분  N_gap 14, N_d 16   Min 0.514 / Max 2.269
4. 벤드 세분  N_arc 32       Min 0.514 / Max 2.269
```

## 출력

* `{step}.msh.h5` — 볼륨 메시
* `{step}.mesh-report.json` — 시도 이력, 존별 셀·품질, 사용된 API 경로, 전체 로그

## ⚠ 첫 실행

PyFluent 의 워크플로우 인자 이름은 릴리스마다 바뀜. 이 모듈은 여러 후보를
순서대로 시도하고 **성공한 경로를 로그와 리포트에 남김**. 실패해도 사용 가능한
경로와 오류를 덤프하므로, 그 리포트를 보면 2025 R1 에 맞게 고정할 수 있음.

첫 실행 후 `mesh-report.json` 의 `stats.api` 와 로그를 확인할 것.
