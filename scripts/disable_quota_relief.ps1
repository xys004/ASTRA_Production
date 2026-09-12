[CmdletBinding()]
param()

$root = Split-Path -Parent $PSScriptRoot
$marker = Join-Path $root "config\quota_relief.enabled"
if (Test-Path -LiteralPath $marker -PathType Leaf) {
    Remove-Item -LiteralPath $marker -Force
    Write-Output "Quota relief disabled. ASTRA returns the synthesizer to codex on its next launch."
    exit 0
}
Write-Output "Quota relief was already disabled."
