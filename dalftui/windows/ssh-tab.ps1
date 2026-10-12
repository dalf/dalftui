#requires -Version 5.1
param(
    [string]$Checkout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
)

# Terminal's Ctrl+Shift+F2 action runs this file in a new tab without depending
# on a personal profile. dssh runs the picker with uv.exe, never a batch shim.
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $Checkout 'bin/profile.ps1')
    dssh
    exit $LASTEXITCODE
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
