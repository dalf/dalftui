#requires -Version 5.1
# Existing Terminal actions target this stable public entrypoint.
$dalftuiWindowsCheckout = [IO.Path]::GetFullPath($PSScriptRoot)
& (Join-Path $dalftuiWindowsCheckout 'dalftui\windows\ssh-tab.ps1') `
    -Checkout $dalftuiWindowsCheckout
exit $LASTEXITCODE
