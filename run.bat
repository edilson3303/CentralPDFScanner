@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python nao foi encontrado.
  echo Instale o Python 3.12 ou mais recente em https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Preparando o programa pela primeira vez...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" app.py
exit /b %errorlevel%

:error
echo.
echo Nao foi possivel preparar o programa.
pause
exit /b 1

