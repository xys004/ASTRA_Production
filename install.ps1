[CmdletBinding()]
param(
    [string]$PythonPath = $env:ASTRA_INSTALL_PYTHON,
    [switch]$SkipShortcut,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-AstraPython {
    param([Parameter(Mandatory = $true)][string]$Candidate)

    try {
        & $Candidate -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Resolve-AstraPython {
    if ($PythonPath) {
        $command = Get-Command $PythonPath -ErrorAction SilentlyContinue
        if (-not $command -or -not (Test-AstraPython $command.Source)) {
            throw "ASTRA_INSTALL_PYTHON/PythonPath must name Python 3.10-3.12: $PythonPath"
        }
        return (& $command.Source -c "import sys; print(sys.executable)").Trim()
    }

    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $candidate = (& $launcher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-AstraPython $candidate.Trim())) {
            return $candidate.Trim()
        }
    }

    foreach ($name in @("python3.12", "python")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and (Test-AstraPython $command.Source)) {
            return (& $command.Source -c "import sys; print(sys.executable)").Trim()
        }
    }

    throw "ASTRA requires Python 3.10-3.12; Python 3.12 is recommended."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "       ASTRA Workstation Setup           " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "`n[1/6] Verifying optional LaTeX..." -ForegroundColor Yellow
if (-not (Get-Command pdflatex -ErrorAction SilentlyContinue)) {
    Write-Host "LaTeX is optional and was not found; browser reports remain available." -ForegroundColor Yellow
} else {
    Write-Host "LaTeX detected." -ForegroundColor Green
}

Write-Host "`n[2/6] Selecting Python..." -ForegroundColor Yellow
$python = Resolve-AstraPython
$pythonIdentity = (& $python -c "import platform,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{platform.machine()}')").Trim()
$pythonDescription = (& $python -c "import platform,sys; print(f'{sys.executable} (Python {platform.python_version()}, {platform.machine()})')").Trim()
Write-Host "Selected interpreter: $pythonDescription" -ForegroundColor Green

Write-Host "`n[3/6] Preparing the virtual environment..." -ForegroundColor Yellow
$venvPath = Join-Path $PSScriptRoot "venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (Test-Path $venvPath) {
    $venvIdentity = ""
    if (Test-Path $venvPython) {
        try {
            $venvIdentity = (& $venvPython -c "import platform,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{platform.machine()}')" 2>$null).Trim()
        } catch {
            $venvIdentity = ""
        }
    }

    if ($venvIdentity -ne $pythonIdentity) {
        $inUse = Get-CimInstance Win32_Process | Where-Object {
            $_.ExecutablePath -and $_.ExecutablePath.StartsWith($venvPath, [System.StringComparison]::OrdinalIgnoreCase)
        }
        if ($inUse) {
            $pids = ($inUse.ProcessId -join ", ")
            throw "The old ASTRA venv is in use by process(es) $pids. Close ASTRA and rerun the installer."
        }

        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backup = Join-Path $PSScriptRoot "venv.backup.$stamp.$PID"
        Move-Item -LiteralPath $venvPath -Destination $backup
        Write-Host "Existing incompatible venv preserved as $backup" -ForegroundColor Cyan
        Invoke-Checked $python @("-m", "venv", $venvPath)
    } else {
        Write-Host "Reusing compatible venv ($venvIdentity)." -ForegroundColor Green
    }
} else {
    Invoke-Checked $python @("-m", "venv", $venvPath)
}

Write-Host "`n[4/6] Installing ASTRA workstation dependencies..." -ForegroundColor Yellow
Invoke-Checked $venvPython @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
Invoke-Checked $venvPython @("-m", "pip", "install", "--only-binary=llvmlite,numba", "-r", "requirements-workstation.txt")

Write-Host "`n[5/6] Preserving or creating the local configuration..." -ForegroundColor Yellow
$envFile = Join-Path $PSScriptRoot ".env"
$envExample = Join-Path $PSScriptRoot ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item -LiteralPath $envExample -Destination $envFile
    Write-Host ".env created from the non-secret example." -ForegroundColor Green
} else {
    Write-Host "Existing .env preserved." -ForegroundColor Green
}

Write-Host "`n[6/6] Configuring local launchers..." -ForegroundColor Yellow
Invoke-Checked $venvPython @("scripts\configure_antigravity_mcp.py")
if (-not $SkipShortcut) {
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcut = $shell.CreateShortcut((Join-Path $desktop "ASTRA.lnk"))
    $shortcut.TargetPath = Join-Path $PSScriptRoot "launch_astra.bat"
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.IconLocation = "powershell.exe"
    $shortcut.Save()
    Write-Host "Desktop shortcut ASTRA.lnk updated." -ForegroundColor Green
}

Write-Host "`nASTRA installation complete on $pythonIdentity." -ForegroundColor Green
Write-Host "Run: .\venv\Scripts\python.exe scripts\astra_doctor.py --remote"
Write-Host "Refresh the ASTRA MCP server in Antigravity after this migration."
if (-not $NonInteractive) {
    Read-Host -Prompt "Press Enter to finish"
}
