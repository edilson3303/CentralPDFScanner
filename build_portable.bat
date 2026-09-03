@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "APP_VENV=.build-venv"
set "APP_DIST=dist\CentralPDFScanner_Portable"

where py >nul 2>nul
if errorlevel 1 (
  echo ERRO: Instale o Python 3.12 ou mais recente.
  pause
  exit /b 1
)

if not exist "%APP_VENV%\Scripts\python.exe" py -3 -m venv "%APP_VENV%"
if errorlevel 1 goto :error

"%APP_VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%APP_VENV%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

if exist build rmdir /s /q build
if exist "dist\CentralPDFScanner" rmdir /s /q "dist\CentralPDFScanner"
if exist "%APP_DIST%" rmdir /s /q "%APP_DIST%"

"%APP_VENV%\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name CentralPDFScanner --add-data "assets\logo_assembleia_legislativa_amapa.png;assets" --collect-all fitz --collect-all pypdf --collect-all pdf2docx --hidden-import cv2 --hidden-import win32com.client app.py
if errorlevel 1 goto :error

ren "dist\CentralPDFScanner" CentralPDFScanner_Portable
mkdir "%APP_DIST%\engines\tesseract" 2>nul

if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
  echo Incluindo Tesseract OCR no pacote portatil...
  xcopy "C:\Program Files\Tesseract-OCR\*" "%APP_DIST%\engines\tesseract\" /E /I /Y >nul
) else (
  echo AVISO: Tesseract nao encontrado. O programa funcionara, mas o OCR ficara desativado.
  echo Instale o Tesseract e execute este arquivo novamente para inclui-lo no pacote.
)

copy /Y "LEIA-ME.txt" "%APP_DIST%\LEIA-ME.txt" >nul
copy /Y "LICENCA.txt" "%APP_DIST%\LICENCA.txt" >nul
if exist "dist\CentralPDFScanner_Portable.zip" del /q "dist\CentralPDFScanner_Portable.zip"
"%APP_VENV%\Scripts\python.exe" -c "import shutil; shutil.make_archive(r'dist\CentralPDFScanner_Portable','zip',r'dist\CentralPDFScanner_Portable')"
if errorlevel 1 goto :error

echo.
echo PRONTO: dist\CentralPDFScanner_Portable.zip
echo Copie esse ZIP para qualquer computador Windows 10 ou 11, extraia e execute CentralPDFScanner.exe.
pause
exit /b 0

:error
echo.
echo ERRO: nao foi possivel gerar o pacote portatil.
pause
exit /b 1
