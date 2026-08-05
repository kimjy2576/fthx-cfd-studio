# 주기 단위셀 — 핀 실형상 (C안: 슬래브 + 측면 케이싱)

포러스를 쓰지 않음. 여기서 j·f 를 직접 뽑아 풀사이즈 포러스 케이스에 공급함.

```bash
cd ~/Desktop/dev/fthx-cfd-studio
./go.sh cell 8                      # 메시 (형상이 바뀌었으므로 재생성 필수)
STAGE=setup ./go.sh cell 8          # 설정 (개명·타입·대칭·BC)
ITER=500 STAGE=solve ./go.sh cell 8 # 반복
python scripts/cell_jf.py examples/cell   # j·f 추출
```

## 도메인 — 전체 피치 + 끝단 슬래브 케이싱

| | |
|---|---|
| x | 176 mm (슬래브 2 + 상류 42 + 코어 44 + 하류 86 + 슬래브 2) |
| y | 0 ~ Pt = 25.40 mm — **symmetry** (관 중심을 지나는 거울면) |
| z | 0 ~ Fp = 1.814 mm — **symmetry** (핀 사이 중앙 거울면), 핀이 중앙 |
| 바디 | 11 (공기 5 · 핀 1 · 관 3 · 케이싱 2) |

**입출구 분리 원리 (C안)**: 상·하류 끝 2mm 슬래브의 측면을 케이싱
solid(0.5mm 액자꼴)로 감싸면 슬래브의 자유면이 입구(출구) 하나만 남음.
Fluent 은 인접 관계가 같은 면을 한 존으로 묶으므로, 자유면이 하나뿐이면
존이 저절로 분리됨 — probe 의 케이싱과 같은 원리이고 API 에 의존하지 않음.

> 이력: 전체 피치만으로 입출구가 분리될 것으로 봤으나 **실측(작업 2578722)
> 결과 측면 자유면과 여전히 한 존으로 묶였음** (up-solid:1 = 2441 mm²
> = 입구 46.08 + 측면 2394.9, 검산 일치). 분리 API 는 메싱·솔버 모두
> 부재(HANDOFF_v3 5절) — 그래서 CAD 로 해결.

측면은 translational periodic 대신 **symmetry** 를 씀 — y=0/Pt 는 관
중심(staggered 도 거울상 성립), z=0/Fp 는 핀 사이 중앙이라 기하적으로
정확한 거울면이고, 짝 맞춤이 필요 없어 존 하나에 측면 4개가 묶여 있어도 걸림.

## 조건

* Re_Dh 489 — **층류**. 난류 모델을 켜면 h 가 과대평가됨
* 핀·관을 등온 280.15 K (냉매측을 풀지 않고 h 만 추출)
* 입구 V_face 2.0 m/s (u_max 가 아님 — D2 이슈)
* 입구면 46.08 mm² (슬래브엔 핀이 없음 — 전체 단면)

## 저널이 하는 일 (setup)

1. 공기-공기 계면 → interior (실측: wall+shadow 로 들어와 유동이 막힘)
2. 슬래브 자유면 개명 → cell_inlet / cell_outlet (이름 기반, 좌표 조회 불필요)
3. 타입 변경 → velocity-inlet / pressure-outlet
4. 측면 → symmetry · 관 → 등온 고정
