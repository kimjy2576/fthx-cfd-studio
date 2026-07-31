# Watertight Geometry 워크플로우 — 설정 순서

Fluent 2025 R1 (Rev 25.1.0) 기준. 튜토리얼(관 1개) 실측으로 확정한 값임.

크기 값은 형상에서 유도됨 — `python -c "from fthx import presets, meshing;
print(meshing.sizing(presets.tutorial()))"` 또는 앱의 튜토리얼 버튼 토스트.

---

## 공통 주의 (여기서 두 번 헛돎)

* 입력란에 숫자를 치면 **Enter 를 누르거나 다른 칸을 클릭**해야 확정됨.
  타이핑만 하고 바로 버튼을 누르면 이전 값으로 실행됨.
* 앞 작업의 값을 바꾸면 **그 작업부터 아래로 다시 실행**해야 함.
  값만 고치고 넘어가면 이전 결과가 그대로 남음.
* 헷갈리면 **File → New** 로 처음부터 하는 게 빠름.

---

## 1. Import Geometry

| 항목 | 값 |
|---|---|
| File Name | `tutorial_1tube.step` |
| Length Unit | **mm** |

→ **Import Geometry** 클릭

확인: 오브젝트 5개(튜토리얼) / 13개(probe), 이름이 `fluid_air_core_r01` 등 유지.
`/objects/list` 로도 확인 가능.

## 2. Add Local Sizing

아무것도 추가하지 않음 → **Update**

> 관벽에 Local Sizing 을 걸면 안 됨. 관 표면은 코어·냉매와 공유되는
> **같은 면**이라 이웃 존까지 조밀해짐 (실측: 69k → 1.31M 셀).

## 3. Generate the Surface Mesh  ← 가장 중요

| 항목 | 값 | 이유 |
|---|---|---|
| Minimum Size | **0.685** | 관벽(0.65mm)이 '틈새'로 인식돼 자동 세분화되는 것을 막는 하한선 |
| Maximum Size | **3.176** | 상·하류 연장부 |
| Growth Rate | 1.2 | |
| **Cells Per Gap** | **1** | 기본 3 이면 관벽을 t/3=0.217mm 로 자동 세분화 |

→ **Generate the Surface Mesh** 클릭

확인: **face 약 26,000**. 수십만이면 값이 반영되지 않은 것임.

## 4. Describe Geometry

| 질문 | 답 |
|---|---|
| Geometry Type | **both fluid and solid regions and/or voids** |
| Apply Share Topology | **Yes** |

→ **Describe Geometry** 클릭

Share Topology 가 동작하면 `fluid_air_core_r01-solid-fluid_air_up-solid` 같은
**계면 존**이 생김. 이것이 바디 간 conformal 접합의 증거임.

## 5. Update Boundaries / Create Regions / Update Regions

기본값 그대로 → 각각 **Update**

## 6. Add Boundary Layers

**건너뜀** (또는 생성된 `smooth-transition_*` 작업을 우클릭 → Delete)

> 경계층은 y+ 목표를 정한 뒤 넣을 항목임. 지금 단계에서 켜면
> 존 충돌 오류가 나기 쉬움.

## 7. Generate the Volume Mesh

| 항목 | 값 |
|---|---|
| Fill With | Poly 또는 Poly-Hexcore |

→ **Generate the Volume Mesh** 클릭

확인 (튜토리얼 기준):

```
셀 존 5개
총 68,641 셀
최소 직교품질 > 0.1
```

---

## 결과 확인 명령

```
/objects/list
/boundary/manage/list
/mesh/check-mesh
```

`/mesh/size-info` 는 2025 R1 에 없음 (`Invalid command`).
볼륨 메시 직후 콘솔에 나오는 `Mesh Statistics` 표가 같은 내용임.

경로를 모르면 `/mesh/` 처럼 슬래시까지만 치고 Enter → 하위 명령 목록이 나옴.
