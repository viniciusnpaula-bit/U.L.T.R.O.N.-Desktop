@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "runtime\python\pythonw.exe" if exist "desktop.py" (
  start "" "%~dp0runtime\python\pythonw.exe" "%~dp0desktop.py"
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" if exist "desktop.py" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0desktop.py"
  exit /b 0
)
if exist "venv\Scripts\pythonw.exe" if exist "desktop.py" (
  start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0desktop.py"
  exit /b 0
)
echo O ULTRON ainda nao esta instalado nesta pasta.
echo Execute o instalador oficial (ULTRON-Setup) e tente de novo.
pause
exit /b 1
