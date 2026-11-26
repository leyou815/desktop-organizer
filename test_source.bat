@echo off
setlocal
set "empty=0"
cd /d "%~dp0"
title Desktop Organizer - Source Test
chcp 65001 >nul

rem ==========================================================
rem  Locate a Python that actually has PyQt5 installed.
rem  If we just call "python" we may hit a different
rem  interpreter, the GUI dies instantly, and the screen is
rem  cleared by "cls" - which looks exactly like "no response".
rem ==========================================================
set "PY_GUI="
call :probe_gui py -3.13
if not defined PY_GUI call :probe_gui py -3
if not defined PY_GUI call :probe_gui py
if not defined PY_GUI call :probe_gui python

set "PY_ANY="
call :probe_any py -3.13
if not defined PY_ANY call :probe_any py -3
if not defined PY_ANY call :probe_any py
if not defined PY_ANY call :probe_any python

:menu
cls
echo.
echo  ==========================================
echo    Desktop Organizer - SOURCE TEST
echo  ==========================================
echo.
echo    GUI python : %PY_GUI%
if not defined PY_GUI echo    GUI python : NOT FOUND - PyQt5 missing
if defined PY_GUI goto menu_body
echo                ^(option 2 / 3 will not work, run option 4^)
:menu_body
echo.
echo    1  Scan preview        (read only, no files moved)
echo    2  Launch app          (test transparency slider)
echo    3  Diagnose            (environment report)
echo    4  Fix Python deps     (pip install PyQt5)
echo    0  Exit
echo.
set "c="
set /p "c=Choice: "
rem  guard: repeated empty reads mean stdin is gone (non-interactive
rem  run). Without this the menu would spin forever.
if defined c set "empty=0"
if not defined c set /a empty+=1
if not defined c if %empty% GEQ 5 exit /b
if "%c%"=="1" goto scan
if "%c%"=="2" goto launch
if "%c%"=="3" goto diag
if "%c%"=="4" goto deps
if "%c%"=="0" exit /b
goto menu

rem ----------------------------------------------------------
rem  subroutines: interpreter probing
rem ----------------------------------------------------------
:probe_gui
if defined PY_GUI exit /b 0
"%~1" %~2 -c "import PyQt5.QtWidgets" >nul 2>&1
if errorlevel 1 exit /b 0
set "PY_GUI=%~1"
if not "%~2"=="" set "PY_GUI=%~1 %~2"
exit /b 0

:probe_any
if defined PY_ANY exit /b 0
"%~1" %~2 -c "import sys" >nul 2>&1
if errorlevel 1 exit /b 0
set "PY_ANY=%~1"
if not "%~2"=="" set "PY_ANY=%~1 %~2"
exit /b 0

rem ----------------------------------------------------------
:scan
cls
echo  === SCAN (no files will be moved) ===
echo.
if defined PY_GUI (
  %PY_GUI% "app\cli.py" scan
) else if defined PY_ANY (
  %PY_ANY% "app\cli.py" scan
) else (
  echo  [X] No Python found in PATH.
)
echo.
echo  ---- finished (any error is printed above) ----
pause
goto menu

rem ----------------------------------------------------------
:launch
cls
echo.
echo  === LAUNCHING ===
echo.
if not defined PY_GUI (
  echo  [X] No Python with PyQt5 found.
  echo      Run option 4 to install it, then try again.
  echo.
  pause
  goto menu
)
echo  python     : %PY_GUI%
echo.
echo  The main window should appear in a second or two.
echo  Closing that window only hides it to the tray.
echo  Right-click the tray icon -^> Exit to quit completely.
echo.
echo  --- app output starts here ---
echo.
%PY_GUI% "app\cli.py" show
set "RC=%ERRORLEVEL%"
echo.
echo  --- app output ends here ---
if not "%RC%"=="0" (
  echo  [X] Exited with code %RC% - read the error text above.
) else (
  echo  [OK] App closed normally.
)
echo.
pause
goto menu

rem ----------------------------------------------------------
:diag
cls
echo  === DIAGNOSE ===
echo.
if defined PY_GUI (
  %PY_GUI% "app\cli.py" diagnose
) else if defined PY_ANY (
  %PY_ANY% "app\cli.py" diagnose
) else (
  echo  [X] No Python found in PATH.
)
echo.
pause
goto menu

rem ----------------------------------------------------------
:deps
cls
echo  === INSTALL PYTHON DEPS ===
echo.
if not defined PY_ANY (
  echo  [X] No Python found in PATH. Install Python 3.13 first.
  echo.
  pause
  goto menu
)
echo  Using: %PY_ANY%
echo.
%PY_ANY% -m pip install PyQt5==5.15.11 -i https://repo.huaweicloud.com/repository/pypi/simple --trusted-host repo.huaweicloud.com
echo.
call :probe_gui py -3.13
call :probe_gui py -3
call :probe_gui py
call :probe_gui python
echo  GUI python is now: %PY_GUI%
if not defined PY_GUI echo  [X] Still missing PyQt5 - copy the pip output above for help.
echo.
pause
goto menu
