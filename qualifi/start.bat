@echo off
rem Double-click (or run from the VS Code terminal) to start Qualifi and open it in the browser.
cd /d "%~dp0"
set PY=python
python --version >nul 2>nul || set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
%PY% -m pip install -q -r requirements.txt
start "" http://localhost:5000
%PY% run.py
pause
