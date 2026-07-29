param(
    [string]$Distro = "Debian",
    [string]$LinuxHome = "/home/nelson"
)

$ErrorActionPreference = "Stop"
$LeanToolchain = "leanprover/lean4:v4.30.0"
$MathlibTag = "v4.30.0"
$MathlibCommit = "c5ea00351c28e24afc9f0f84379aa41082b1188f"
$BenchRoot = "$LinuxHome/astra-benchmarks"
$MathlibRoot = "$BenchRoot/mathlib4-$MathlibTag"
$Elan = "$LinuxHome/.elan/bin/elan"
$Lake = "$LinuxHome/.elan/bin/lake"

function Invoke-Wsl {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AsRoot,
        [string]$WorkingDirectory = ""
    )
    $prefix = @("-d", $Distro)
    if ($AsRoot) {
        $prefix += @("-u", "root")
    }
    if ($WorkingDirectory) {
        $prefix += @("--cd", $WorkingDirectory)
    }
    & wsl.exe @prefix -- @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed with exit code $LASTEXITCODE."
    }
}

Invoke-Wsl -AsRoot -Arguments @("apt-get", "update")
Invoke-Wsl -AsRoot -Arguments @(
    "env",
    "DEBIAN_FRONTEND=noninteractive",
    "apt-get",
    "install",
    "-y",
    "ca-certificates",
    "curl",
    "git",
    "maxima",
    "cadabra2"
)

& wsl.exe -d $Distro -- test -x $Elan
if ($LASTEXITCODE -ne 0) {
    Invoke-Wsl -Arguments @(
        "curl",
        "-sSfL",
        "https://elan.lean-lang.org/elan-init.sh",
        "-o",
        "/tmp/elan-init.sh"
    )
    Invoke-Wsl -Arguments @(
        "sh",
        "/tmp/elan-init.sh",
        "-y",
        "--default-toolchain",
        "none",
        "--no-modify-path"
    )
}

Invoke-Wsl -Arguments @(
    $Elan,
    "toolchain",
    "install",
    $LeanToolchain
)
Invoke-Wsl -Arguments @("mkdir", "-p", $BenchRoot)

& wsl.exe -d $Distro -- test -d "$MathlibRoot/.git"
if ($LASTEXITCODE -ne 0) {
    Invoke-Wsl -Arguments @(
        "git",
        "clone",
        "--filter=blob:none",
        "--branch",
        $MathlibTag,
        "https://github.com/leanprover-community/mathlib4.git",
        $MathlibRoot
    )
}

Invoke-Wsl -Arguments @(
    "git",
    "-C",
    $MathlibRoot,
    "fetch",
    "--depth",
    "1",
    "origin",
    $MathlibTag
)
Invoke-Wsl -Arguments @(
    "git",
    "-C",
    $MathlibRoot,
    "checkout",
    "--detach",
    $MathlibCommit
)
Invoke-Wsl -WorkingDirectory $MathlibRoot -Arguments @(
    $Lake,
    "exe",
    "cache",
    "get"
)

Invoke-Wsl -WorkingDirectory $MathlibRoot -Arguments @(
    $Lake,
    "env",
    "lean",
    "--version"
)
Invoke-Wsl -Arguments @(
    "git",
    "-C",
    $MathlibRoot,
    "rev-parse",
    "HEAD"
)
Invoke-Wsl -Arguments @("maxima", "--version")
Invoke-Wsl -Arguments @("dpkg-query", "-W", "cadabra2")
