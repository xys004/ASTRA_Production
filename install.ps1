# ASTRA Production Installation Script
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "    ASTRA Production Setup Script        " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "`n[1/4] Verifying Python Installation..." -ForegroundColor Yellow
$pythonExists = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExists) {
    Write-Host "ERROR: Python is not installed or not in your system PATH." -ForegroundColor Red
    Write-Host "Please download Python 3.9+ from https://www.python.org/downloads/ and check 'Add Python to PATH'."
    Write-Host "Installation aborted." -ForegroundColor Red
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}
Write-Host "Python detected!" -ForegroundColor Green

Write-Host "`n[2/4] Creating Python Virtual Environment (venv)..." -ForegroundColor Yellow
python -m venv venv

Write-Host "`n[3/4] Installing Math Solvers and LLM SDKs..." -ForegroundColor Yellow
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "`n[4/4] Creating Desktop Shortcut..." -ForegroundColor Yellow
$WshShell = New-Object -comObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$Shortcut = $WshShell.CreateShortcut("$DesktopPath\ASTRA Production Wizard.lnk")
$Shortcut.TargetPath = "cmd.exe"
$Shortcut.Arguments = "/k cd /d `"$PSScriptRoot`" && .\venv\Scripts\python.exe wizard_production.py"
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.IconLocation = "powershell.exe"
$Shortcut.Save()
Write-Host "Shortcut created on your Desktop." -ForegroundColor Green

Write-Host "`n=========================================" -ForegroundColor Green
Write-Host "  ASTRA Installation Complete!           " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green

Write-Host "`nInstallation was successful. You can now close this window and double-click the 'ASTRA Production Wizard' shortcut on your Desktop." -ForegroundColor Cyan
Read-Host -Prompt "Press Enter to finish"
