@echo off
setlocal
echo =========================================
echo     ASTRA Production Setup Script (CMD)
echo =========================================

echo.
echo [1/4] Verifying Python Installation...
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python is not installed or not in your system PATH.
    echo Please download Python 3.9+ from https://www.python.org/downloads/ and check 'Add Python to PATH'.
    echo Installation aborted.
    pause
    exit /b 1
)
echo Python detected!

echo.
echo [2/4] Creating Python Virtual Environment (venv)...
python -m venv venv

echo.
echo [3/4] Installing Math Solvers, LLM SDKs, and Web Studio...
call .\venv\Scripts\python.exe -m pip install --upgrade pip
call .\venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo [4/4] Creating Desktop Shortcut...
set VBS_SCRIPT="%TEMP%\CreateShortcut.vbs"
echo Set oWS = WScript.CreateObject("WScript.Shell") > %VBS_SCRIPT%
echo sLinkFile = "%USERPROFILE%\Desktop\ASTRA Production Wizard.lnk" >> %VBS_SCRIPT%
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> %VBS_SCRIPT%
echo oLink.TargetPath = "cmd.exe" >> %VBS_SCRIPT%
echo oLink.Arguments = "/k cd /d """%~dp0""" && .\venv\Scripts\python.exe wizard_production.py" >> %VBS_SCRIPT%
echo oLink.WorkingDirectory = "%~dp0" >> %VBS_SCRIPT%
echo oLink.Save >> %VBS_SCRIPT%
cscript //nologo %VBS_SCRIPT%
del %VBS_SCRIPT%
echo Shortcut created on your Desktop.

echo.
echo =========================================
echo   ASTRA Installation Complete!           
echo =========================================
echo.
echo Installation was successful. You can now close this window and double-click the 'ASTRA Production Wizard' shortcut on your Desktop.
pause
