# 실행 방법

Fluent Meshing 은 `.py` 저널을 **내장 파이썬**으로 실행함.
**서버에 아무것도 설치할 필요가 없음.**

## 0) 파일 옮기고 압축 풀기

```bash
cd ~
unzip fthx_case.zip
cd fthx_case
ls          # model.step  mesh.py  case.json  RUN.md  settings.txt
```

## 1) 실행 — 이 블록을 통째로 복사

```bash
cd ~/fthx_case
fluent 3d -meshing -g -t8 -i mesh.py
```

LSF 큐에 제출되고 `Job <번호> is submitted to queue` 가 뜸.
허용 코어 수는 **1 / 2 / 4 / 8 / 32 / 128 / 256 / 512** 중 하나여야 함.

> ⚠ **코어 수가 셀 수에 영향을 줌.** 병렬 분할 경계에서 메시가 달라지기 때문임.
> probe 실측: 4코어 164,461 → 32코어 229,026 (**+39%**).
> 케이스 간 비교를 할 때는 `-t` 값을 반드시 고정할 것.

## 2) 상태 확인

```bash
bjobs                       # PEND=대기, RUN=실행중, 없으면 완료
```

## 3) 결과 확인

```bash
cd ~/fthx_case
ls -lt *.trn *.lsflog | head

# 단계별 성공/실패
grep -E "^(>>>|<<<)" $(ls -t *.trn | head -1)

# 셀 수·품질
grep -E "cells were created|Orthogonal Quality|Total Number of Cell Zones" $(ls -t *.trn | head -1)

# 메시 파일이 저장됐는지
ls -lh mesh.msh.h5

# 오류
grep -iE "error|warning" $(ls -t *.trn | head -1) | head -20
```

## 4) 해석 설정 (M3)

메시가 나온 뒤:

```bash
fluent 3ddp -g -t8 -i setup.py
```

포러스 계수·경계조건·물성이 형상과 운전 조건에서 유도돼 들어감.
`closure.json` 에 그 값들이 정리되어 있음.

## 5) 판정

| 항목 | 기대값 |
|---|---|
| 셀 존 수 | **16** (STEP 바디 수와 같아야 함) |
| 셀 수 | 약 0.20 M (범위 0.16~0.24) |
| 최소 직교품질 | > 0.10 |

셀 존 수가 다르면 임포트나 Share Topology 가 실패한 것임.

---

## 저널이 쓰는 값

형상에서 유도됨. 손으로 고칠 것 없음.

| | 값 |
|---|---|
| Minimum Size | **0.685** mm |
| Maximum Size | **3.176** mm |
| Growth Rate | 1.2 |
| **Cells Per Gap** | **1** |
| Share Topology | Yes |
| 경계층 | 없음 |
| Fill | polyhedra |

`Cells Per Gap` 이 핵심임. 기본값 3 이면 관벽(0.65 mm)을 틈새로
인식해 t/3 까지 자동 세분화하고, 셀이 20 배로 늘어남 (2025 R1 실측).

## 저널이 실패하면

각 단계가 `>>> 단계명` / `<<< OK` 또는 `<<< FAIL` 로 로그에 찍힘.
FAIL 이 난 단계와 그 아래 traceback 을 그대로 보내면 고칠 수 있음.
저널은 실패해도 다음 단계로 진행하므로 **한 번 실행으로 모든 문제를 파악**할 수 있음.

## GUI 로 직접 할 때

`settings.txt` 에 넣을 값이 정리되어 있음.
