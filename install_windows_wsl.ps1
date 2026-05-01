# ASTRA Production clean Windows installer.
# Runs from Windows PowerShell. Installs/checks WSL, bootstraps Ubuntu packages,
# creates a WSL Python venv, installs Python requirements, and creates a
# Windows Desktop shortcut that launches ASTRA through WSL.

param(
    [string]$Distro = "Ubuntu",
    [switch]$SkipWslInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ShortcutName = "ASTRA Production Wizard (WSL).lnk"
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath $ShortcutName

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command($Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Convert-ToWslPath($WindowsPath) {
    $resolved = (Resolve-Path $WindowsPath).Path
    $drive = $resolved.Substring(0, 1).ToLower()
    $rest = $resolved.Substring(2).Replace("\", "/")
    return "/mnt/$drive$rest"
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "    ASTRA Production WSL Installer       " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Step "Checking WSL"
if (-not (Test-Command "wsl")) {
    if ($SkipWslInstall) {
        throw "wsl.exe was not found and -SkipWslInstall was supplied."
    }
    Write-Host "WSL is not installed. Requesting Windows to install WSL + $Distro."
    Write-Host "If Windows asks for a restart, reboot and run this installer again." -ForegroundColor Yellow
    wsl --install -d $Distro
    Read-Host "Press Enter after WSL installation/restart is complete"
}

Write-Step "Checking distro: $Distro"
$distros = (wsl -l -q) -join "`n"
if ($distros -notmatch [regex]::Escape($Distro)) {
    if ($SkipWslInstall) {
        throw "WSL distro '$Distro' is not installed."
    }
    Write-Host "Installing WSL distro $Distro."
    wsl --install -d $Distro
    Read-Host "Finish the Ubuntu first-run setup, then press Enter"
}

$ProjectWsl = Convert-ToWslPath $ProjectRoot
$Bootstrap = "$ProjectWsl/scripts/bootstrap_wsl.sh"

Write-Step "Bootstrapping ASTRA inside WSL"
wsl -d $Distro bash -lc "cd '$ProjectWsl' && chmod +x '$Bootstrap' && '$Bootstrap'"

Write-Step "Creating Windows Desktop shortcut"
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "C:\Windows\System32\wsl.exe"
$Shortcut.Arguments = "-d $Distro -- bash -lc ""cd '$ProjectWsl' && source .astra-wsl-venv/bin/activate && python wizard_production.py"""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.IconLocation = "powershell.exe"
$Shortcut.Save()

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  ASTRA WSL installation complete        " -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host "Shortcut created: $ShortcutPath" -ForegroundColor Green
Write-Host "Use this shortcut for clean company/institution installs." -ForegroundColor Cyan
Read-Host "Press Enter to finish"
