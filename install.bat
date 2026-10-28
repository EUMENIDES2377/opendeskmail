@echo off
cd /d "%~dp0"
if exist "python-runtime\python.exe" (
  "python-runtime\python.exe" setup_local.py
  goto finished
)
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 setup_local.py
goto finished
:use_python
python setup_local.py
:finished
if errorlevel 1 echo Install Python 3.10+ with Tkinter from https://www.python.org/downloads/windows/ then retry.
pause
