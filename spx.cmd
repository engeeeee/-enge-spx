@echo off
setlocal
if exist "%~dp0dist\ENGE-SPX\spx.exe" (
  "%~dp0dist\ENGE-SPX\spx.exe" %*
  exit /b
)
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Start ENGE SPX once with Start-Windows.cmd to prepare Python.
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0src\entry.py" %*
exit /b %errorlevel%

