# ASTRA Production Installation Script
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "    ASTRA Production Setup Script        " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "`n[1/5] Verifying LaTeX Installation (Optional)..." -ForegroundColor Yellow
$latexExists = Get-Command pdflatex -ErrorAction SilentlyContinue
if (-not $latexExists) {
    Write-Host "NOTE: LaTeX (pdflatex) is not installed." -ForegroundColor Yellow
    Write-Host "ASTRA will render reports in the browser using MathJax."
    Write-Host "To enable PDF report export, install MiKTeX from https://miktex.org/download"
} else {
    Write-Host "LaTeX detected. ASTRA will compile PDF reports for validated theorems." -ForegroundColor Green
}

Write-Host "`n[2/5] Verifying Python Installation..." -ForegroundColor Yellow
$pythonExists = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonExists) {
    Write-Host "ERROR: Python is not installed or not in your system PATH." -ForegroundColor Red
    Write-Host "Download Python 3.9+ from https://www.python.org/downloads/ and check 'Add Python to PATH'."
    Write-Host "Installation aborted." -ForegroundColor Red
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}
$pyVersion = python --version 2>&1
Write-Host "Python detected: $pyVersion" -ForegroundColor Green

Write-Host "`n[3/5] Creating Python Virtual Environment (venv)..." -ForegroundColor Yellow
python -m venv venv
Write-Host "Virtual environment ready." -ForegroundColor Green

Write-Host "`n[4/5] Installing dependencies..." -ForegroundColor Yellow
.\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host "Dependencies installed." -ForegroundColor Green

Write-Host "`n[4b] Setting up .env configuration..." -ForegroundColor Yellow
$envFile     = Join-Path $PSScriptRoot ".env"
$envExample  = Join-Path $PSScriptRoot ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Host ".env created from .env.example." -ForegroundColor Green
        Write-Host "      You can add API keys via Settings in the web interface." -ForegroundColor Cyan
    } else {
        Write-Host "WARNING: .env.example not found. Create a .env file manually." -ForegroundColor Yellow
    }
} else {
    Write-Host ".env already exists. Skipping." -ForegroundColor Green
}

Write-Host "`n[5/5] Creating Desktop Shortcut..." -ForegroundColor Yellow
$WshShell  = New-Object -comObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$Shortcut  = $WshShell.CreateShortcut("$DesktopPath\ASTRA Production.lnk")
$Shortcut.TargetPath     = Join-Path $PSScriptRoot "launch_astra.bat"
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.IconLocation   = "powershell.exe"
$Shortcut.Save()
Write-Host "Desktop shortcut 'ASTRA Production' created." -ForegroundColor Green

Write-Host "`n=========================================" -ForegroundColor Green
Write-Host "  ASTRA Installation Complete!           " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host "`nDouble-click 'ASTRA Production' on your Desktop to launch." -ForegroundColor Cyan
Write-Host "The browser will open at http://127.0.0.1:5050 automatically." -ForegroundColor Cyan
Write-Host "Click Settings (top-right) to enter your API key." -ForegroundColor Cyan
Read-Host -Prompt "`nPress Enter to finish"
