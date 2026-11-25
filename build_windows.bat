@echo off
rem ============================================================
rem  Build a standalone .exe with PyInstaller
rem  Output: dist\DesktopOrganizer.exe
rem ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] Installing PyInstaller if needed...
python -m pip install --upgrade pyinstaller >nul || goto :err

echo [2/3] Building...
python -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name DesktopOrganizer ^
  --icon "assets\icon.ico" ^
  --add-data "app;app" ^
  --add-data "assets;assets" ^
  app\cli.py || goto :err

echo [3/3] Done.
echo   dist\DesktopOrganizer.exe
echo.
echo Note: the exe still reads config from %%APPDATA%%\DesktopOrganizer
goto :end

:err
echo.
echo Build failed. Make sure Python and PyInstaller are installed.
pause
exit /b 1

:end
pause
endlocal
