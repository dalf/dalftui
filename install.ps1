#requires -Version 5.1
<#
.SYNOPSIS
Install dssh, its host picker, and the Windows Terminal SSH/VS Code shortcuts.
.EXAMPLE
.\install.ps1
.EXAMPLE
.\install.ps1 -PackageManager choco
.EXAMPLE
.\install.ps1 -SkipFzf
.EXAMPLE
.\install.ps1 -VSCodePath 'C:\Tools\VS Code Portable'
#>
[CmdletBinding()]
param(
    [ValidateSet('auto', 'winget', 'choco')][string]$PackageManager = 'auto',
    [switch]$SkipFzf,
    [string]$VSCodePath,
    [string]$ProfilePath,
    [switch]$SkipTerminal,
    [string[]]$TerminalSettingsPath
)

$dalftuiSetupWasDotSourced = $MyInvocation.InvocationName -eq '.'
$dalftuiSetupCheckout = [IO.Path]::GetFullPath($PSScriptRoot)
. (Join-Path $dalftuiSetupCheckout 'dalftui\windows\setup.ps1')

if (-not $dalftuiSetupWasDotSourced) {
    try {
        Invoke-DalftuiWindowsSetup -Preference $PackageManager -Skip:$SkipFzf `
            -TargetProfile $ProfilePath -Checkout $dalftuiSetupCheckout `
            -NoTerminal:$SkipTerminal -SettingsPaths $TerminalSettingsPath `
            -SelectedVSCodePath $VSCodePath
    } catch {
        Write-Error ("Setup failed: " + $_.Exception.Message) -ErrorAction Continue
        exit 1
    }
}
