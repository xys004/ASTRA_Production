# ASTRA Production Installation Script
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "    ASTRA Production Setup Script        " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "`n[1/3] Creating Python Virtual Environment (venv)..." -ForegroundColor Yellow
python -m venv venv

Write-Host "`n[2/3] Upgrading pip..." -ForegroundColor Yellow
.\venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host "`n[3/3] Installing Math Solvers and LLM SDKs..." -ForegroundColor Yellow
.\venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "`n=========================================" -ForegroundColor Green
Write-Host "  ASTRA Installation Complete!           " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green

Write-Host "`nNext Steps:"
Write-Host "1. Activate your environment: " -NoNewline; Write-Host ".\venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "2. Export your API keys (e.g. `$env:GEMINI_API_KEY='your-key'`)"
Write-Host "3. Start the orchestrator: " -NoNewline; Write-Host "python main.py" -ForegroundColor Cyan
