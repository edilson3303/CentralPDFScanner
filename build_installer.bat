@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "dist\CentralPDFScanner_Portable\CentralPDFScanner.exe" (
  echo ERRO: Execute primeiro build_portable.bat.
  pause
  exit /b 1
)

set "APP_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%APP_ISCC%" set "APP_ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%APP_ISCC%" (
  echo ERRO: Instale o Inno Setup 6 para gerar o instalador.
  pause
  exit /b 1
)

"%APP_ISCC%" installer.iss
if errorlevel 1 (
  echo ERRO: nao foi possivel gerar o instalador.
  pause
  exit /b 1
)

echo.
echo PRONTO: dist\installer\PDF_Scanner_ALAP_Setup_v2.6.0.exe
pause
