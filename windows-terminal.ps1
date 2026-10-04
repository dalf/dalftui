#requires -Version 5.1
# A new Terminal tab runs this file without depending on a personal profile.
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'windows.ps1')
    dssh
    exit $LASTEXITCODE
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
