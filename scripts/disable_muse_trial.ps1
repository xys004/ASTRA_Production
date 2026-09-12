[CmdletBinding()]
param()

$root = Split-Path -Parent $PSScriptRoot
$marker = Join-Path $root "config\muse_trial.enabled"
if (Test-Path -LiteralPath $marker -PathType Leaf) {
    Remove-Item -LiteralPath $marker -Force
    Write-Output "Muse trial disabled. ASTRA will use the preceding .env configuration on its next launch."
    exit 0
}
Write-Output "Muse trial was already disabled."
