[CmdletBinding()]
param()

$root = Split-Path -Parent $PSScriptRoot
$marker = Join-Path $root "config\quota_relief.enabled"
$overlay = Join-Path $root "config\quota_relief.env"
$museMarker = Join-Path $root "config\muse_trial.enabled"
if (-not (Test-Path -LiteralPath $overlay -PathType Leaf)) {
    throw "Quota-relief overlay is missing: $overlay"
}
if (Test-Path -LiteralPath $museMarker -PathType Leaf) {
    throw "Muse trial is enabled; disable it first (both set ASTRA_ARCHITECTURE_PROFILE)."
}
New-Item -ItemType File -Path $marker -Force | Out-Null
Set-Content -LiteralPath $marker -Value "Enabled locally on $(Get-Date -Format 'yyyy-MM-dd HH:mm zzz')." -Encoding utf8
Write-Output "Quota relief enabled (synthesizer -> agy). Verify with .\venv\Scripts\python.exe .\scripts\astra_doctor.py --json before a cycle."
