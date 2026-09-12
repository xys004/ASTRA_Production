[CmdletBinding()]
param()

$root = Split-Path -Parent $PSScriptRoot
$marker = Join-Path $root "config\muse_trial.enabled"
$overlay = Join-Path $root "config\muse_trial.env"
$quotaMarker = Join-Path $root "config\quota_relief.enabled"
if (-not (Test-Path -LiteralPath $overlay -PathType Leaf)) {
    throw "Muse trial overlay is missing: $overlay"
}
if (Test-Path -LiteralPath $quotaMarker -PathType Leaf) {
    throw "Quota relief is enabled; disable it first (both set ASTRA_ARCHITECTURE_PROFILE)."
}
New-Item -ItemType File -Path $marker -Force | Out-Null
Set-Content -LiteralPath $marker -Value "Enabled locally on $(Get-Date -Format 'yyyy-MM-dd HH:mm zzz')." -Encoding utf8
Write-Output "Muse trial enabled. Verify with .\venv\Scripts\python.exe .\scripts\astra_doctor.py --json before a cycle."
