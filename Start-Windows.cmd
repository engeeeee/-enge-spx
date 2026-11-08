@echo off
setlocal
cd /d "%~dp0"
if exist "dist\ENGE-SPX\ENGE-SPX.exe" (
  start "" "dist\ENGE-SPX\ENGE-SPX.exe"
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto fail
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
start "" ".venv\Scripts\pythonw.exe" "src\entry.py"
exit /b
:fail
echo ENGE SPX could not prepare Python. Install Python 3.12+ with Tcl/Tk and the Python Launcher.
pause
exit /b 1

