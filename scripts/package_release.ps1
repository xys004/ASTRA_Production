# Build a compact ASTRA/ASTRUM source ZIP for distribution.
# The ZIP intentionally excludes virtual environments, workspace outputs,
# caches, git metadata, and local secrets.

param(
    [string]$Name = "ASTRUM-Production",
    [string]$Version = "dev"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistDir = Join-Path $ProjectRoot "dist"
$StagingRoot = Join-Path $DistDir "$Name-$Version"
$ZipPath = Join-Path $DistDir "$Name-$Version.zip"

if (Test-Path $StagingRoot) {
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force
}
if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

New-Item -ItemType Directory -Path $StagingRoot | Out-Null

$ExcludeDirs = @(
    ".git",
    "__pycache__",
    "venv",
    "env",
    ".astra-wsl-venv",
    "workspace",
    "dist"
)
$ExcludeFiles = @(
    ".env",
    "*.pyc",
    "*.pyo",
    "*.zip"
)

Get-ChildItem -Path $ProjectRoot -Force | ForEach-Object {
    $name = $_.Name
    if ($_.PSIsContainer -and $ExcludeDirs -contains $name) {
        return
    }
    foreach ($pattern in $ExcludeFiles) {
        if ($name -like $pattern) {
            return
        }
    }
    Copy-Item -LiteralPath $_.FullName -Destination $StagingRoot -Recurse -Force
}

New-Item -ItemType Directory -Path (Join-Path $StagingRoot "workspace") | Out-Null
New-Item -ItemType File -Path (Join-Path $StagingRoot "workspace/.keep") | Out-Null

Compress-Archive -Path (Join-Path $StagingRoot "*") -DestinationPath $ZipPath -Force

Write-Host "Release ZIP created:" -ForegroundColor Green
Write-Host $ZipPath
