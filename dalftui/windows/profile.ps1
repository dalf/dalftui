#requires -Version 5.1
param(
    [string]$Checkout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
)

# Loaded by the PowerShell profile; the implementation follows this checkout.
$dalftuiPickerPath = Join-Path $Checkout 'bin/ssh_picker.py'
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

# Bash-like line editing. Setting EditMode resets every key handler, so this
# runs before Oh My Posh and the editor shortcut add theirs, and only when the
# mode differs, which keeps bindings made after an earlier switch.
if (Get-Command Set-PSReadLineOption -ErrorAction SilentlyContinue) {
    if ((Get-PSReadLineOption).EditMode -ne 'Emacs') { Set-PSReadLineOption -EditMode Emacs }
    Set-PSReadLineKeyHandler -Chord 'Ctrl+LeftArrow' -Function BackwardWord
    Set-PSReadLineKeyHandler -Chord 'Ctrl+RightArrow' -Function ForwardWord
    Set-PSReadLineOption -HistorySearchCursorMovesToEnd
    # PSReadLine 2.0 (Windows PowerShell 5.1) and the legacy console lack predictions.
    try { Set-PSReadLineOption -PredictionSource History -ErrorAction Stop } catch { }
}

# Draw the prompt with the Oh My Posh theme shared with Linux.
if (Get-Command oh-my-posh -CommandType Application -ErrorAction SilentlyContinue) {
    oh-my-posh init pwsh --config (Join-Path $Checkout 'config/oh-my-posh.omp.json') | Invoke-Expression
}

# Terminal sends the same Ctrl+B, F3 sequence used by remote tmux. Locally,
# Ctrl+B keeps its Emacs meaning (back one character) and F3 opens the folder
# without inserting or executing command-line text.
$dalftuiEditorPath = Join-Path $Checkout 'bin/vscode.py'
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
    Set-PSReadLineKeyHandler -Chord 'F3', 'Ctrl+Shift+F3' `
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
