# push 후 검증 루틴 (OpenFOAM 경로)

Claude 가 push 할 때마다 아래 순서로 확인함. 1·2단계는 매번, 3단계는 형상이
바뀐 커밋에서만.

## 1단계 — 회귀 + STL 생성 (Windows PowerShell, ~1분)

```powershell
cd fthx-cfd-studio
git pull
python -m pytest tests/ -q          # 103+ passed 확인
python scripts/make_stl.py          # 전 프리셋 → out_foam/<프리셋>/
```

`make_stl.py` 가 예외 없이 `[OK]` 를 찍으면 내장 검증
(watertight · STL↔CAD 면적오차<0.1% · 인벤토리 1:1) 통과임.
여기서 실패하면 2단계로 가지 말고 에러 전문을 회신.

## 2단계 — OpenFOAM 자체 검사 (WSL, ~1분)

1단계와 독립된 구현(surfaceCheck)으로 교차검증. snappyHexMesh 가 실제
소비자이므로 이것이 최종 판정.

```bash
source /usr/lib/openfoam/openfoam2412/etc/bashrc   # .bashrc 에 있으면 생략
cd /mnt/c/<레포 경로>/fthx-cfd-studio
bash scripts/verify_stl.sh out_foam
```

기대: 전 파일 `[PASS]`, 마지막 줄 `FAIL 0 · UNKNOWN 0`.
`[FAIL]`/`[????]` 가 있으면 표시된 로그 파일 내용을 회신.

주의: 검사만 하는 것이므로 `/mnt/c` 에서 바로 실행해도 됨.
(느려지는 것은 snappy/솔버 실행이며, 그때만 `~/cases` 로 복사)

## 3단계 — 육안 확인 (ParaView, 형상 변경 커밋만)

커밋 메시지에 **[geom]** 태그가 있으면 수행:

1. ParaView 에서 `out_foam/probe/*.stl` 전체 열기 (다중 선택)
2. 확인: 벤드↔관 끝 맞물림 · 코어 박스의 관 구멍 · 상·하류 박스 접합
3. 어긋난 부분은 스크린샷으로 회신

## 회신 형식 (2단계 기준)

```
1단계: 103 passed / make_stl [OK] 2건
2단계: PASS 18 · FAIL 0 · UNKNOWN 0
(3단계 해당 시: 이상 없음 / 스크린샷 첨부)
```

이 세 줄이면 다음 단계 착수 가능.
