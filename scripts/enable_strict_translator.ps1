[CmdletBinding()]
param()

$root = Split-Path -Parent $PSScriptRoot
$marker = Join-Path $root "config\strict_translator.enabled"
$overlay = Join-Path $root "config\strict_translator.env"
if (-not (Test-Path -LiteralPath $overlay -PathType Leaf)) {
    throw "Strict-translator overlay is missing: $overlay"
}
# Composable overlay: it only sets ASTRA_TRANSLATOR_STRICT_CONTRACT, so it may
# coexist with muse_trial or quota_relief. No mutual-exclusion guard needed.
New-Item -ItemType File -Path $marker -Force | Out-Null
Set-Content -LiteralPath $marker -Value "Enabled locally on $(Get-Date -Format 'yyyy-MM-dd HH:mm zzz')." -Encoding utf8
Write-Output "Strict translator contract enabled (translator + repairer). Takes effect on the next cycle; restart the MCP server if one is running."
