#requires -Version 5.1
param(
    [string]$Checkout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
)

# Loaded by the PowerShell profile; the implementation follows this checkout.
$dalftuiPickerPath = Join-Path $Checkout 'bin/ssh_picker.py'
$dalftuiCommand = {
    [CmdletBinding()]
    param([Parameter(Position = 0)][ValidateNotNullOrEmpty()][string]$HostName)

    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $uv) {
        throw 'uv is required. Install it (scoop install uv), then open a new PowerShell window.'
    }
    $pythonArguments = @('run', '--no-project', '--python', '>=3.11', $dalftuiPickerPath)
    if ($PSBoundParameters.ContainsKey('HostName')) {
        $pythonArguments += @('--connect', $HostName)
    } else {
        $pythonArguments += '--pick'
    }
    & $uv.Source @pythonArguments
}.GetNewClosure()
Set-Item -Path Function:\global:dssh -Value $dalftuiCommand

# Unix-like commands. clear, pwd and man are built in. An alias to a tool that
# setup does not install exists only when the tool does. Windows PowerShell 5.1
# makes ls and wget AllScope aliases, which Set-Alias replaces only with AllScope.
foreach ($dalftuiAlias in @(@('ls', 'lsd'), @('wget', 'wget2'), @('htop', 'btop'), @('sudo', 'gsudo'),
                             @('notepad', 'notepad++'))) {
    if (Get-Command $dalftuiAlias[1] -CommandType Application -ErrorAction SilentlyContinue) {
        Set-Alias -Name $dalftuiAlias[0] -Value $dalftuiAlias[1] -Option AllScope -Scope Global
    }
}
# Windows' own curl lacks HTTP/2, SFTP and more, and 5.1's curl is Invoke-WebRequest.
$dalftuiCurl = Get-Command curl -CommandType Application -All -ErrorAction SilentlyContinue |
    Where-Object { $_.Source -notlike "$env:SystemRoot\*" } | Select-Object -First 1
if ($dalftuiCurl) { Set-Alias -Name curl -Value $dalftuiCurl.Source -Option AllScope -Scope Global }
if (Get-Command bat -CommandType Application -ErrorAction SilentlyContinue) {
    Remove-Item Alias:cat -ErrorAction SilentlyContinue
    function global:cat { $input | & bat --style=plain @args }
}

function global:touch {
    foreach ($path in $args) {
        if (Test-Path -LiteralPath $path) { (Get-Item -LiteralPath $path).LastWriteTime = Get-Date }
        else { $null = New-Item -ItemType File -Path $path }
    }
}

function global:du {
    param (
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Paths = @(".")  # Default to current directory
    )

    # Unix flags such as -sh are not paths; du always summarizes.
    $Paths = @($Paths | Where-Object { $_ -notmatch '^-' })
    if (-not $Paths) { $Paths = @('.') }

    # Expand wildcards; -Force also finds hidden items such as AppData
    $resolvedPaths = @()
    foreach ($p in $Paths) {
        $expanded = Get-Item $p -Force -ErrorAction SilentlyContinue
        if ($expanded) {
            $resolvedPaths += $expanded
        } else {
            Write-Warning "'$p' not found or matched no items."
        }
    }

    # Remove duplicates and calculate size
    $seen = @{}
    foreach ($entry in $resolvedPaths) {
        if ($seen.ContainsKey($entry.FullName)) { continue }
        $seen[$entry.FullName] = $true

        $totalSize = (Get-ChildItem -Path $entry.FullName -Recurse -Force -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        $sizeMB = [math]::Round($totalSize / 1MB, 2)
        "{0,10:N2} MB {1}" -f $sizeMB, $entry.FullName
    }
}

function global:df {
    function Format-Size($bytes) {
        if ($bytes -ge 1GB) { return "{0:N2} GB" -f ($bytes / 1GB) }
        elseif ($bytes -ge 1MB) { return "{0:N2} MB" -f ($bytes / 1MB) }
        elseif ($bytes -ge 1KB) { return "{0:N2} KB" -f ($bytes / 1KB) }
        else { return "$bytes B" }
    }

    # A drive that is not ready (empty card reader) has no Used value.
    $drives = Get-PSDrive -PSProvider 'FileSystem' | Where-Object { $null -ne $_.Used } | ForEach-Object {
        $total = $_.Used + $_.Free
        $used = $_.Used
        $free = $_.Free
        $percentUsed = if ($total -ne 0) { [math]::Round(($used / $total) * 100, 0) } else { 0 }

        [PSCustomObject]@{
            Drive     = $_.Name
            Used      = Format-Size $used
            Free      = Format-Size $free
            Total     = Format-Size $total
            Percent   = "$percentUsed%"
            Root      = $_.Root
        }
    }

    $drives | Format-Table `
        @{Label="Drive";     Expression={$_.Drive};     Alignment='Right'}, `
        @{Label="    Total"; Expression={$_.Total};     Alignment='Right'}, `
        @{Label="     Used"; Expression={$_.Used};      Alignment='Right'}, `
        @{Label="     Free"; Expression={$_.Free};      Alignment='Right'}, `
        @{Label="% Used";    Expression={$_.Percent};   Alignment='Right'}, `
        @{Label="Root";    Expression={$_.Root};      Alignment='Left'}
}

function global:wc {
    # A simple function: an advanced one binds -w to -WarningAction.
    $lineCount = $false
    $wordCount = $false
    $byteCount = $false
    $files = @()

    foreach ($arg in $args) {
        if ($arg -match '^-[lwc]+$') {
            if ($arg -match 'l') { $lineCount = $true }
            if ($arg -match 'w') { $wordCount = $true }
            if ($arg -match 'c') { $byteCount = $true }
        } else {
            $found = Get-Item $arg -Force -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer }
            if ($found) { $files += $found } else { Write-Error "File not found: $arg" }
        }
    }

    if (-not ($lineCount -or $wordCount -or $byteCount)) {
        $lineCount = $wordCount = $byteCount = $true
    }

    $pipeline = @($input)
    if ($files.Count -eq 0 -and $pipeline.Count -eq 0) {
        Write-Error "Usage: wc [-l] [-w] [-c] file1 [file2 ...]"
        return
    }

    $totalLines = 0
    $totalWords = 0
    $totalBytes = 0

    if ($files.Count -eq 0) {
        # Piped text has no file size; -c counts characters plus line ends.
        $lines = $pipeline.Count
        $words = ($pipeline -join "`n" -split '\s+').Where({ $_ -ne '' }).Count
        $bytes = ($pipeline | Measure-Object -Character).Characters + $lines
        $output = @()
        if ($lineCount) { $output += $lines }
        if ($wordCount) { $output += $words }
        if ($byteCount) { $output += $bytes }
        return $output -join "`t"
    }

    foreach ($file in $files) {
        $content = Get-Content -LiteralPath $file.FullName
        $lines = $content.Count
        $words = ($content -join "`n" -split '\s+').Where({ $_ -ne '' }).Count
        $bytes = $file.Length

        $totalLines += $lines
        $totalWords += $words
        $totalBytes += $bytes

        $output = @()
        if ($lineCount) { $output += $lines }
        if ($wordCount) { $output += $words }
        if ($byteCount) { $output += $bytes }

        $output += $file.Name
        $output -join "`t"
    }

    # Show totals if more than one file
    if ($files.Count -gt 1) {
        $output = @()
        if ($lineCount) { $output += $totalLines }
        if ($wordCount) { $output += $totalWords }
        if ($byteCount) { $output += $totalBytes }

        $output += "total"
        $output -join "`t"
    }
}
# Keep a real du, df or wc, such as Git for Windows' usr\bin tools.
foreach ($dalftuiName in @('du', 'df', 'wc')) {
    if (Get-Command $dalftuiName -CommandType Application -ErrorAction SilentlyContinue) {
        Remove-Item -Path "Function:\$dalftuiName"
    }
}

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

# Activate mise unless the personal profile already did. It must come before
# Oh My Posh, whose prompt otherwise stops showing failed exit codes.
if ((Get-Command mise -CommandType Application -ErrorAction SilentlyContinue) -and
    -not (Test-Path -Path Function:\_mise_hook)) {
    # Windows PowerShell 5.1 lacks the directory-change hook; mise warns every session.
    if ($PSVersionTable.PSVersion.Major -lt 7 -and -not $env:MISE_PWSH_CHPWD_WARNING) { $env:MISE_PWSH_CHPWD_WARNING = '0' }
    # mise prints nothing when it cannot start, such as without the VC++ runtime.
    $dalftuiMise = & mise activate pwsh | Out-String
    if ($dalftuiMise.Trim()) { Invoke-Expression $dalftuiMise }
}

# Draw the prompt with the Oh My Posh theme shared with Linux. Its init needs
# PSReadLine, which is missing when PSModulePath is empty.
if ((Get-Command oh-my-posh -CommandType Application -ErrorAction SilentlyContinue) -and
    (Get-Command Get-PSReadLineOption -ErrorAction SilentlyContinue)) {
    oh-my-posh init pwsh --config (Join-Path $Checkout 'config/oh-my-posh.omp.json') | Invoke-Expression
}

# Ctrl+B, F2 and Ctrl+B, F3 / v are tmux keys. PSReadLine handles them at a local
# prompt without inserting or executing command-line text.
$dalftuiEditorPath = Join-Path $Checkout 'bin/vscode.py'
$dalftuiOpenFolder = {
    $location = Get-Location
    if ($location.Provider.Name -ne 'FileSystem') {
        throw 'VS Code needs a filesystem directory. Change to a folder first.'
    }
    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $uv) { throw 'uv is required to open VS Code.' }
    # Keep the editor's error text: a key handler discards a program's error output.
    # Under Stop, Windows PowerShell 5.1 would throw on the first captured error line.
    $ErrorActionPreference = 'Continue'
    $errors = @()
    & $uv.Source run --no-project --python '>=3.11' $dalftuiEditorPath --folder $location.ProviderPath 2>&1 |
        ForEach-Object { if ($_ -is [System.Management.Automation.ErrorRecord]) { $errors += "$_" } else { $_ } }
    if ($global:LASTEXITCODE -ne 0) {
        $message = (($errors -join "`n") -replace '(?m)^VS Code: ', '').Trim()
        throw $(if ($message) { $message } else { 'Could not open VS Code.' })
    }
}.GetNewClosure()
Set-Item -Path Function:\global:Open-DalftuiCurrentFolder -Value $dalftuiOpenFolder
# A key handler's output is redirected, so the picker runs as its own console process.
$dalftuiPick = {
    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $uv) { throw 'uv is required. Install it (scoop install uv), then open a new PowerShell window.' }
    Start-Process -FilePath $uv.Source -NoNewWindow -Wait -ArgumentList @(
        'run', '--no-project', '--python', '>=3.11', ('"' + $dalftuiPickerPath + '"'), '--pick')
}.GetNewClosure()
Set-Item -Path Function:\global:Start-DalftuiSshPicker -Value $dalftuiPick

if (Get-Command Set-PSReadLineKeyHandler -ErrorAction SilentlyContinue) {
    # Like tmux, Ctrl+B is a prefix; Ctrl+B Ctrl+B moves back one character.
    Set-PSReadLineKeyHandler -Chord 'Ctrl+b,Ctrl+b' -Function BackwardChar
    Set-PSReadLineKeyHandler -Chord 'Ctrl+b,F2' `
        -BriefDescription 'DalftuiSshPicker' `
        -Description 'Choose an SSH host with dssh; keep the input line' `
        -ScriptBlock {
            [Console]::WriteLine()  # Output and errors go below the input line, not under the redrawn prompt.
            $previousExitCode = $global:LASTEXITCODE
            try { Start-DalftuiSshPicker }
            catch { [Console]::Error.WriteLine('dssh: ' + $_.Exception.Message) }
            finally { $global:LASTEXITCODE = $previousExitCode }
            [Microsoft.PowerShell.PSConsoleReadLine]::InvokePrompt($null, [Console]::CursorTop)
        }
    foreach ($chord in 'Ctrl+b,F3', 'Ctrl+b,v') {
        Set-PSReadLineKeyHandler -Chord $chord `
            -BriefDescription 'DalftuiOpenFolderInCode' `
            -Description 'Open the current directory in VS Code; keep the input line' `
            -ScriptBlock {
                [Console]::WriteLine()  # Output and errors go below the input line, not under the redrawn prompt.
                $previousExitCode = $global:LASTEXITCODE
                try { Open-DalftuiCurrentFolder | Out-Host }
                catch { [Console]::Error.WriteLine('VS Code: ' + $_.Exception.Message) }
                finally { $global:LASTEXITCODE = $previousExitCode }
                [Microsoft.PowerShell.PSConsoleReadLine]::InvokePrompt($null, [Console]::CursorTop)
            }
    }
}
