@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  "python-runtime\python.exe" setup_local.py
  if errorlevel 1 exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0demo.py"
