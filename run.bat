@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo   ============================================
echo    FT-HX CFD Studio
echo   ============================================
echo.

REM ---------- 1) Python 찾기 ----------
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto :no_python

REM ---------- 2) 가상환경 ----------
set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo   [1/3] 가상환경 생성 중...
  "%PY%" -m venv .venv
  if errorlevel 1 goto :venv_fail
) else (
  echo   [1/3] 가상환경 확인됨
)

REM ---------- 3) 의존성 ----------
"%VPY%" -c "import fastapi, uvicorn, pydantic, numpy, scipy" >nul 2>nul
if errorlevel 1 (
  echo   [2/3] 의존성 설치 중... cadquery 가 커서 몇 분 걸릴 수 있음
  "%VPY%" -m pip install --upgrade pip -q
  "%VPY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :pip_fail
) else (
  echo   [2/3] 의존성 확인됨
)

REM 선택 패키지 안내 (없어도 서버는 뜸)
"%VPY%" -c "import cadquery" >nul 2>nul
if errorlevel 1 echo         · cadquery 없음 - STEP 생성 비활성 ^(pip install cadquery^)
"%VPY%" -c "import CoolProp" >nul 2>nul
if errorlevel 1 echo         · CoolProp 없음 - 물성 조회 비활성 ^(pip install CoolProp^)

REM ---------- 4) 실행 ----------
echo   [3/3] 서버 시작 - http://127.0.0.1:8020
echo         종료는 Ctrl+C
echo.
"%VPY%" run.py --reload %*
set "RC=%errorlevel%"
if not "%RC%"=="0" if not "%RC%"=="130" goto :run_fail
goto :end

REM ---------- 오류 처리 ----------
:no_python
echo   [오류] Python 을 찾을 수 없음.
echo          https://www.python.org/downloads/ 에서 3.10 이상을 설치하고
echo          설치 시 "Add python.exe to PATH" 를 체크할 것.
goto :hold

:venv_fail
echo   [오류] 가상환경 생성 실패. .venv 폴더를 지운 뒤 다시 실행해 볼 것.
goto :hold

:pip_fail
echo   [오류] 의존성 설치 실패. 네트워크/프록시를 확인할 것.
echo          최소 구성만 설치하려면:
echo          .venv\Scripts\python.exe -m pip install pydantic numpy scipy fastapi uvicorn
goto :hold

:run_fail
echo.
echo   [오류] 서버가 코드 %RC% 로 종료됨.
echo          포트가 사용 중이면: run.bat --port 8021
goto :hold

:hold
echo.
pause

:end
endlocal
