#requires -Version 5.1
param(
    [string]$Checkout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
)

# Loaded by the PowerShell profile; the implementation follows this checkout.
$dalftuiPickerPath = Join-Path $Checkout 'ssh-picker.py'
$dalftuiCommand = {
    [CmdletBinding()]
    param([Parameter(Position = 0)][ValidateNotNullOrEmpty()][string]$HostName)

    $python = Get-Command py -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $pythonArguments = @('-3', $dalftuiPickerPath)
    if (-not $python) {
        $python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        $pythonArguments = @($dalftuiPickerPath)
    }
    if (-not $python) {
        throw 'Python 3.11+ is required. Install Python, then open a new PowerShell window.'
    }
    if ($PSBoundParameters.ContainsKey('HostName')) {
        $pythonArguments += @('--connect', $HostName)
    } else {
        $pythonArguments += '--pick'
    }
    & $python.Source @pythonArguments
}.GetNewClosure()
Set-Item -Path Function:\global:dssh -Value $dalftuiCommand

# Terminal sends the same Ctrl+B, F3 sequence used by remote tmux. PSReadLine
# handles it at a local prompt without inserting or executing command-line text.
$dalftuiEditorPath = Join-Path $Checkout 'vscode.py'
$dalftuiOpenFolder = {
    $location = Get-Location
    if ($location.Provider.Name -ne 'FileSystem') {
        throw 'VS Code needs a filesystem directory. Change to a folder first.'
    }
    $python = Get-Command py -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $arguments = @('-3', $dalftuiEditorPath, '--folder', $location.ProviderPath)
    if (-not $python) {
        $python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        $arguments = @($dalftuiEditorPath, '--folder', $location.ProviderPath)
    }
    if (-not $python) { throw 'Python 3.11+ is required to open VS Code.' }
    & $python.Source @arguments
    if ($global:LASTEXITCODE -ne 0) { throw 'Could not open VS Code; see the error above.' }
}.GetNewClosure()
Set-Item -Path Function:\global:Open-DalftuiCurrentFolder -Value $dalftuiOpenFolder

if (Get-Command Set-PSReadLineKeyHandler -ErrorAction SilentlyContinue) {
    Set-PSReadLineKeyHandler -Chord 'Ctrl+b,F3', 'Ctrl+Shift+F3' `
        -BriefDescription 'DalftuiOpenFolderInCode' `
        -Description 'Open the current directory in VS Code; keep the input line' `
        -ScriptBlock {
            $previousExitCode = $global:LASTEXITCODE
            try { Open-DalftuiCurrentFolder | Out-Host }
            catch { [Console]::Error.WriteLine('VS Code: ' + $_.Exception.Message) }
            finally { $global:LASTEXITCODE = $previousExitCode }
            [Microsoft.PowerShell.PSConsoleReadLine]::InvokePrompt()
        }
}
