#requires -Version 5.1
# Loaded by the PowerShell profile; the implementation follows this checkout.
$dalftuiPickerPath = Join-Path $PSScriptRoot 'ssh-picker.py'
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
    $global:LASTEXITCODE = $LASTEXITCODE
}.GetNewClosure()
Set-Item -Path Function:\global:dssh -Value $dalftuiCommand
