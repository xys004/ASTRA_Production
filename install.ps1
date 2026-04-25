# ASTRA Production Installation Script
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "    ASTRA Production Setup Script        " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "`n[1/5] Verifying LaTeX Installation (Optional)..." -ForegroundColor Yellow
$latexExists = Get-Command pdflatex -ErrorAction SilentlyContinue
if (-not $latexExists) {
    Write-Host "NOTE: LaTeX (pdflatex) is not installed." -ForegroundColor Yellow
    Write-Host "ASTRA will use MathJax in the Web Browser for visualization."
    Write-Host "If you want ASTRA to automatically compile PDF reports of theorems, install MiKTeX from https://miktex.org/download"
} else {
    Write-Host "LaTeX detected! ASTRA will automatically compile PDF reports for validated theorems." -ForegroundColor Green
}

Write-Host "`n[2/5] Verifying Python Installation..." -ForegroundColor Yellow
$pythonExists = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExists) {
    Write-Host "ERROR: Python is not installed or not in your system PATH." -ForegroundColor Red
    Write-Host "Please download Python 3.9+ from https://www.python.org/downloads/ and check 'Add Python to PATH'."
    Write-Host "Installation aborted." -ForegroundColor Red
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}
Write-Host "Python detected!" -ForegroundColor Green

Write-Host "`n[3/5] Creating Python Virtual Environment (venv)..." -ForegroundColor Yellow
python -m venv venv

Write-Host "`n[4/5] Installing Math Solvers, LLM SDKs, and Web Studio..." -ForegroundColor Yellow
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "`n[5/5] Creating Desktop Shortcut..." -ForegroundColor Yellow
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
