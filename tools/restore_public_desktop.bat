@echo off
rem Restore public-desktop shortcuts that an older version moved into the shelf.
rem Safe to delete this file after it succeeds.
chcp 65001 >nul
cd /d "%~dp0.."
python "tools\restore_public_desktop.py" --yes
echo.
pause
