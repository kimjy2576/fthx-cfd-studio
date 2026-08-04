# 주기 단위셀 — 핀 실형상

포러스를 쓰지 않음. 여기서 j·f 를 직접 뽑아 풀사이즈 포러스 케이스에 공급함.

```bash
cd ~/Desktop/dev/fthx-cfd-studio
./go.sh cell 8                      # 메시 (약 1.5M 셀)
STAGE=setup ./go.sh cell 8          # 설정
ITER=500 STAGE=solve ./go.sh cell 8 # 반복
```

## 도메인 — 전체 피치 + translational periodic

| | |
|---|---|
| x | 176 mm (상류 44 + 코어 44 + 하류 88) |
| y | 0 ~ Pt = 25.40 mm — **periodic** |
| z | 0 ~ Fp = 1.814 mm — **periodic**, 핀이 중앙 |

**입출구가 유일한 자유면**이므로 Fluent 이 별도 존으로 만들어 줌.

> 대칭 1/4 (y Pt/2, z Fp/2) 로도 만들 수 있으나(`periodic=False`) 그 경우
> 입구면이 대칭면과 한 존으로 묶여 BC 를 걸 수 없음. Fluent 은 인접 관계가
> 같은 면을 묶고, `meshing_utilities` 에 좌표 기반 면존 분리 함수가 없음이
> 실측으로 확인됨. 셀은 4배가 되지만 그래서 전체 피치를 씀.

## 조건

* Re_Dh 489 — **층류**. 난류 모델을 켜면 h 가 과대평가됨
* 핀·관을 등온 280.15 K (냉매측을 풀지 않고 h 만 추출)
* 공기측 전열면적 1937 mm² = 0.001937 m²
* 바디 7개 — 공기 3 · 핀 1 · 관 3(걸친 관이 a/b 로 나뉨)

## 결과

`cell_results.csv` → `python scripts/cell_jf.py examples/cell`
