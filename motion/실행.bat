@echo off
chcp 65001 >nul
rem 윈도우에서 이 파일을 더블클릭하면 실행된다.
rem 영상 파일을 이 파일 위로 끌어다 놓아도 된다.
cd /d "%~dp0.."
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo 파이썬이 없다. https://www.python.org/downloads/ 에서 설치할 것.
  echo 설치할 때 "Add Python to PATH" 를 반드시 체크해야 한다.
  pause
  exit /b 1
)
%PY% motion\start.py %*
echo.
pause
