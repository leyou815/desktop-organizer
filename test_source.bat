@echo off
cd /d "%~dp0"
title Desktop Organizer - Source Test
chcp 65001 >nul

:menu
cls
echo.
echo  ==========================================
echo    Desktop Organizer - SOURCE TEST
echo  ==========================================
echo.
echo    1  Scan preview (read only)
echo    2  Launch app (test transparency slider)
echo    0  Exit
echo.
set /p "c=Choice: "
if "%c%"=="1" goto scan
if "%c%"=="2" goto launch
if "%c%"=="0" exit /b
goto menu

:scan
cls
echo  === SCAN (no files will be moved) ===
echo.
python app\cli.py scan
echo.
pause
goto menu

:launch
cls
echo  === LAUNCHING ===
echo  Drag the transparency slider in the main window.
echo  Closing the window only hides it to tray.
echo  Right-click tray icon -^> Exit to quit completely.
echo.
python app\cli.py show
goto menu
