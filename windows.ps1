#requires -Version 5.1
# Loaded by the PowerShell profile; keep this stable public entrypoint.
$dalftuiWindowsCheckout = [IO.Path]::GetFullPath($PSScriptRoot)
. (Join-Path $dalftuiWindowsCheckout 'dalftui\windows\profile.ps1') `
    -Checkout $dalftuiWindowsCheckout
