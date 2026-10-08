#requires -Version 5.1
<#
.SYNOPSIS
Install dssh, its host picker, and the PowerShell and Windows Terminal settings, or remove them with -Uninstall.
.EXAMPLE
.\install.ps1
.EXAMPLE
.\install.ps1 -VSCodePath 'C:\Tools\VS Code Portable'
.EXAMPLE
.\install.ps1 -Uninstall -DryRun
#>
[CmdletBinding()]
param(
    [string]$VSCodePath,
    [string]$ProfilePath,
    [switch]$SkipTerminal,
    [string[]]$TerminalSettingsPath,
    [switch]$Uninstall,
    [switch]$DryRun
)

$dalftuiSetupWasDotSourced = $MyInvocation.InvocationName -eq '.'
$dalftuiSetupCheckout = [IO.Path]::GetFullPath($PSScriptRoot)
. (Join-Path $dalftuiSetupCheckout 'dalftui\windows\setup.ps1')

if (-not $dalftuiSetupWasDotSourced) {
    try {
        Invoke-DalftuiWindowsSetup -TargetProfile $ProfilePath -Checkout $dalftuiSetupCheckout `
            -NoTerminal:$SkipTerminal -SettingsPaths $TerminalSettingsPath `
            -SelectedVSCodePath $VSCodePath -Uninstall:$Uninstall -DryRun:$DryRun
    } catch {
        $action = if ($Uninstall) { 'Uninstall' } else { 'Setup' }
        Write-Error ("$action failed: " + $_.Exception.Message) -ErrorAction Continue
        exit 1
    }
}
