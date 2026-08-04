# 주기 단위셀 — 핀 실형상

포러스를 쓰지 않음. 여기서 j·f 를 직접 뽑아 풀사이즈 포러스 케이스에 공급함.

```bash
cd ~/Desktop/dev/fthx-cfd-studio
./go.sh cell 8                      # 메시 (약 376k 셀)
STAGE=setup ./go.sh cell 8          # 설정
ITER=500 STAGE=solve ./go.sh cell 8 # 반복
```

## 도메인

| | |
|---|---|
| x | 176 mm (상류 + 코어 + 하류) |
| y | 0 ~ Pt/2 = 12.70 mm — 양쪽 다 관 중심(대칭) |
| z | 0 ~ Fp/2 = 0.907 mm — 핀 두께 중앙 ~ 핀 사이 중앙 |

네 측면이 모두 대칭면이라 주기 경계가 필요 없음.

## 조건

* Re_Dh 489 — **층류**. 난류 모델을 켜면 h 가 과대평가됨
* 핀·관 표면 등온 280.15 K (냉매측을 풀지 않고 h 만 추출)
* 공기측 전열면적 0.000510 m2
* 바디 6개

## 결과

`cell_results.csv` → `python scripts/cell_jf.py examples/cell`
