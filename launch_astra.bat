@echo off
title ASTRA Production - Web Studio
cd /d "%~dp0"

echo.
echo  ============================================
echo   ASTRA Production - Web Studio
echo   http://127.0.0.1:5050
echo  ============================================
echo.

:: Activate virtual environment
call venv\Scripts\activate

:: Open browser after ~2s delay (background)
start /b cmd /c "ping 127.0.0.1 -n 4 > nul && start http://127.0.0.1:5050"

:: Launch Flask — logs appear in this window
python web\app.py

echo.
echo  ASTRA se ha detenido. Presiona cualquier tecla para cerrar.
pause > nul
