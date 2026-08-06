# 주기 단위셀 — 핀 실형상 (A안: 메싱 TUI 각도분리 라벨링)

포러스를 쓰지 않음. 여기서 j·f 를 직접 뽑아 풀사이즈 포러스 케이스에 공급함.

```bash
cd ~/Desktop/dev/fthx-cfd-studio
./go.sh cell 8                      # ① 메시 (cell.msh.h5)
STAGE=label ./go.sh cell 8          # ② 라벨 (분리·개명 → cell_labeled.msh.h5)
STAGE=setup ./go.sh cell 8          # ③ 설정 (interior·타입·대칭·BC)
ITER=500 STAGE=solve ./go.sh cell 8 # ④ 반복
python scripts/cell_jf.py examples/cell   # j·f 추출
```

## 도메인 — 전체 피치 (순수 주기셀)

| | |
|---|---|
| x | 176 mm (상류 44 + 코어 44 + 하류 88) |
| y | 0 ~ Pt = 25.40 mm — **symmetry** (관 중심을 지나는 거울면) |
| z | 0 ~ Fp = 1.814 mm — **symmetry** (핀 사이 중앙 거울면), 핀이 중앙 |
| 바디 | 7 (공기 3 · 핀 1 · 관 3) |

**입출구 분리 (A안, label 단계)**: Fluent 이 입구를 측면과 한 존으로
묶어 내놓지만, 메싱 TUI `/boundary/separate/sep-face-zone-by-angle` 에
존을 **`(id)` 리스트 문법**으로 주면 법선차 90°인 조각들(입구+측면4)로
갈라짐 (실측 2580749 — 괄호 없는 id 는 "Invalid entity" 로 전패).
분리 후 기대 면적 46.08 mm² 조각을 `cell_inlet`/`cell_outlet` 으로 개명해
`cell_labeled.msh.h5` 로 저장. 저장 전 기존 파일을 지움 — write_mesh 가
overwrite 프롬프트에 걸리면 [OK] 를 돌려주고도 실제 저장을 안 함 (실측).

> 이력: "분리 API 부재" 는 조사 범위 오류였음 (meshing_utilities 서비스만
> 보고 TUI 메뉴를 안 봄). 그 오판으로 만든 C안(끝단 슬래브+케이싱)은
> A안 확정으로 철회 (eb2fcd9 → revert). 솔버 쪽도
> `sep_face_zone_angle`("by" 없는 정식명)로 가능함이 실측됨(2580752) —
> setup 저널이 라벨 없는 메시를 받으면 이 경로로 폴백함.

측면은 translational periodic 대신 **symmetry** — y=0/Pt 는 관
중심(staggered 도 거울상 성립), z=0/Fp 는 핀 사이 중앙이라 기하적으로
정확한 거울면이고, 짝 맞춤이 필요 없음. 각도분리 덕에 측면 4개도 각자
존으로 갈라져 있어 필요하면 진짜 periodic 도 걸 수 있음.

## 조건

* Re_Dh 489 — **층류**. 난류 모델을 켜면 h 가 과대평가됨
* 핀·관을 등온 280.15 K (냉매측을 풀지 않고 h 만 추출)
* 입구 V_face 2.0 m/s (u_max 가 아님 — D2 이슈)
* 입구면 46.08 mm² (x=0 엔 핀이 없어 전체 단면)

## setup 저널이 하는 일

1. 공기-공기 계면 → interior (실측: wall+shadow 로 들어와 유동이 막힘)
2. cell_inlet/cell_outlet 확인 (없으면 B안 폴백: 솔버 각도분리+면적판정)
3. 타입 변경 → velocity-inlet / pressure-outlet
4. 측면 → symmetry · 관 → 등온 고정
