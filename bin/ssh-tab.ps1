#requires -Version 5.1
# Launch a Windows Terminal SSH tab from this checkout.
$dalftuiWindowsCheckout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
& (Join-Path $dalftuiWindowsCheckout 'dalftui\windows\ssh-tab.ps1') `
    -Checkout $dalftuiWindowsCheckout
exit $LASTEXITCODE
