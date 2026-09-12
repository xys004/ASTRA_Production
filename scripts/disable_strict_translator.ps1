[CmdletBinding()]
param()

$root = Split-Path -Parent $PSScriptRoot
$marker = Join-Path $root "config\strict_translator.enabled"
if (Test-Path -LiteralPath $marker -PathType Leaf) {
    Remove-Item -LiteralPath $marker -Force
    Write-Output "Strict translator contract disabled. ASTRA returns to the base translator prompt on its next launch."
    exit 0
}
Write-Output "Strict translator contract was already disabled."
