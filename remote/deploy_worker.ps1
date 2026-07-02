param(
    [Parameter(Mandatory=$true)]
    [string]$Remote,

    [string]$WorkerDir = "~/astra-worker",

    [string]$IdentityFile = "$env:USERPROFILE\.ssh\google_compute_engine",

    [switch]$NoTailscaleProxy
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SshOptions = @("-o", "StrictHostKeyChecking=accept-new")

if (Test-Path -LiteralPath $IdentityFile) {
    $SshOptions += @("-i", $IdentityFile)
}

if (-not $NoTailscaleProxy) {
    $SshOptions += @("-o", "ProxyCommand=tailscale nc %h %p")
}

ssh @SshOptions $Remote "mkdir -p $WorkerDir"
scp @SshOptions "$ProjectRoot\requirements.txt" "${Remote}:$WorkerDir/requirements.txt"
scp @SshOptions "$PSScriptRoot\astra_remote_worker.py" "${Remote}:$WorkerDir/astra_remote_worker.py"
scp @SshOptions "$PSScriptRoot\bootstrap_ubuntu_worker.sh" "${Remote}:$WorkerDir/bootstrap_ubuntu_worker.sh"
ssh @SshOptions $Remote "chmod +x $WorkerDir/bootstrap_ubuntu_worker.sh && ASTRA_WORKER_DIR=$WorkerDir $WorkerDir/bootstrap_ubuntu_worker.sh"

Write-Host ""
Write-Host "Remote worker deployed."
Write-Host "Use these settings in ASTRA .env:"
Write-Host "ASTRA_ORACLE_MODE=remote"
Write-Host "ASTRA_REMOTE_HOST=$Remote"
Write-Host "ASTRA_REMOTE_PYTHON=$WorkerDir/venv/bin/python"
Write-Host "ASTRA_REMOTE_WORKER=$WorkerDir/astra_remote_worker.py"
Write-Host "ASTRA_REMOTE_WORKDIR=$WorkerDir/workspace"
Write-Host "ASTRA_REMOTE_SSH_OPTIONS=-i $IdentityFile -o ProxyCommand=`"tailscale nc %h %p`""
