#requires -Version 5.1
param(
    [string]$Checkout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
)

# A new Terminal tab runs this file without depending on a personal profile.
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $Checkout 'bin/profile.ps1')
    dssh
    exit $LASTEXITCODE
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
