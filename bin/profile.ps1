#requires -Version 5.1
# Load the PowerShell profile implementation from this checkout.
$dalftuiWindowsCheckout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $dalftuiWindowsCheckout 'dalftui\windows\profile.ps1') `
    -Checkout $dalftuiWindowsCheckout
