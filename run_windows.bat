@echo off
rem ============================================================
rem  Desktop Organizer - quick start (no install)
rem  Requires: Python 3.8+ with PyQt5  ->  pip install -r requirements.txt
rem ============================================================
setlocal
cd /d "%~dp0"

set "PYW=pythonw"
where pythonw >nul 2>nul || set "PYW=python"

start "" %PYW% "app\cli.py" run
if errorlevel 1 (
    echo.
    echo Failed to start. Try running this in a terminal to see the error:
    echo     python app\cli.py run
    pause
)
endlocal
