#requires -Version 5.1
<#
.SYNOPSIS
Install the Windows dssh command and its fzf host picker.
.EXAMPLE
.\setup-windows.ps1
.EXAMPLE
.\setup-windows.ps1 -PackageManager choco
.EXAMPLE
.\setup-windows.ps1 -SkipFzf
#>
[CmdletBinding()]
param(
    [ValidateSet('auto', 'winget', 'choco')][string]$PackageManager = 'auto',
    [switch]$SkipFzf,
    [string]$ProfilePath = $PROFILE.CurrentUserCurrentHost
)

function Find-DalftuiApplication([string]$Name) {
    Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Update-DalftuiProcessPath {
    $entries = @($env:PATH,
        [Environment]::GetEnvironmentVariable('PATH', 'User'),
        [Environment]::GetEnvironmentVariable('PATH', 'Machine'))
    $env:PATH = ($entries | Where-Object { $_ }) -join [IO.Path]::PathSeparator
}

function Select-DalftuiPackageManager([string]$Preference = 'auto') {
    if ($Preference -ne 'auto') {
        $command = Find-DalftuiApplication $Preference
        if (-not $command) {
            throw "$Preference was not found. Install fzf manually or choose an available package manager."
        }
        return $command
    }
    foreach ($name in @('winget', 'choco')) {
        $command = Find-DalftuiApplication $name
        if ($command) { return $command }
    }
    return $null
}

function Invoke-DalftuiPackageInstall($Manager) {
    if ([IO.Path]::GetFileNameWithoutExtension($Manager.Name) -eq 'winget') {
        & $Manager.Source install --id junegunn.fzf --exact --source winget `
            --accept-package-agreements --accept-source-agreements | Out-Host
    } else {
        & $Manager.Source install fzf --yes --no-progress | Out-Host
    }
    if ($LASTEXITCODE -ne 0) {
        throw "fzf installation failed (exit $LASTEXITCODE). For Chocolatey, use an administrator PowerShell if required, then rerun setup."
    }
}

function Install-DalftuiFzf([string]$Preference = 'auto', [switch]$Skip) {
    if (Find-DalftuiApplication 'fzf') {
        Write-Host 'fzf is already available; keeping the installed version.'
        return $true
    }
    if ($Skip) { return $false }
    $manager = Select-DalftuiPackageManager $Preference
    if (-not $manager) {
        Write-Warning 'Install fzf with: winget install --id junegunn.fzf --exact OR choco install fzf. Then open a new terminal. Direct connections with dssh HOST are available meanwhile.'
        return $false
    }
    Write-Host "Installing fzf using $($manager.Name) ..."
    Invoke-DalftuiPackageInstall $manager
    Update-DalftuiProcessPath
    if (-not (Find-DalftuiApplication 'fzf')) {
        throw 'The package manager finished, but fzf is not on PATH. Open a new terminal and rerun setup.'
    }
    return $true
}

function Write-DalftuiProfile([string]$Path, [string]$Checkout) {
    $Path = [IO.Path]::GetFullPath($Path)
    $loader = Join-Path $Checkout 'windows.ps1'
    if (-not (Test-Path -LiteralPath $loader -PathType Leaf)) {
        throw "The Windows command loader is missing: $loader"
    }
    $content = ''
    if (Test-Path -LiteralPath $Path) {
        # Detect BOMs (including Windows PowerShell's UTF-16 default). Without a
        # BOM, use the current shell's default encoding to preserve its text.
        $reader = [IO.StreamReader]::new($Path, [Text.Encoding]::Default, $true)
        try { $content = $reader.ReadToEnd() } finally { $reader.Dispose() }
    }
    $newline = [Environment]::NewLine
    if ($content.Contains("`r`n")) { $newline = "`r`n" }
    elseif ($content.Contains("`n")) { $newline = "`n" }
    $begin = '# >>> dalftui >>>'
    $end = '# <<< dalftui <<<'
    $block = $begin + $newline + ". '" + $loader.Replace("'", "''") + "'" + $newline + $end
    $starts = [regex]::Matches($content, '(?m)^# >>> dalftui >>>\r?$')
    $ends = [regex]::Matches($content, '(?m)^# <<< dalftui <<<\r?$')
    if ($starts.Count -or $ends.Count) {
        if ($starts.Count -ne 1 -or $ends.Count -ne 1 -or $ends[0].Index -le $starts[0].Index) {
            throw "The dalftui block in $Path is incomplete or duplicated. Repair its markers before rerunning setup."
        }
        $after = $ends[0].Index + $ends[0].Length
        # Keep the existing end marker's CR as part of its following CRLF.
        if ($content[$after - 1] -eq "`r") { $after-- }
        $updated = $content.Substring(0, $starts[0].Index) + $block + $content.Substring($after)
    } else {
        $updated = $content
        if ($updated.Length -and -not $updated.EndsWith("`n")) { $updated += $newline }
        $updated += $block + $newline
    }
    if ($updated -eq $content) {
        Write-Host 'PowerShell profile already configured.'
        return
    }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $backup = $Path + '.dalftui-' + [guid]::NewGuid().ToString('N') + '.bak'
        [IO.File]::Copy($Path, $backup)
        Write-Host "Profile backup: $backup"
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    # A BOM lets both PowerShell 5.1 and 7 read Unicode checkout paths correctly.
    [IO.File]::WriteAllText($Path, $updated, [Text.UTF8Encoding]::new($true))
    Write-Host "PowerShell profile configured: $Path"
}

function Invoke-DalftuiWindowsSetup {
    [CmdletBinding()]
    param([string]$Preference = 'auto', [switch]$Skip, [string]$TargetProfile,
          [string]$Checkout = $PSScriptRoot)
    $ErrorActionPreference = 'Stop'
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'This setup script targets Windows. On Linux, use ./install.'
    }
    $python = Find-DalftuiApplication 'py'
    $pythonArguments = @('-3')
    if (-not $python) {
        $python = Find-DalftuiApplication 'python'
        $pythonArguments = @()
    }
    if (-not $python) { throw 'Install Python 3.11+ first, then open a new terminal.' }
    & $python.Source @pythonArguments -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
    $ssh = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
    if (-not (Test-Path -LiteralPath $ssh) -and -not (Find-DalftuiApplication 'ssh')) {
        throw 'Install the Windows OpenSSH client first, then rerun setup.'
    }
    Update-DalftuiProcessPath
    $pickerReady = Install-DalftuiFzf -Preference $Preference -Skip:$Skip
    Write-DalftuiProfile -Path $TargetProfile -Checkout $Checkout
    . (Join-Path $Checkout 'windows.ps1')
    if (-not (Find-DalftuiApplication 'code')) {
        Write-Warning 'For Ctrl+B, F3, install VS Code with its code command on PATH and the Remote - SSH extension.'
    }
    Write-Host 'dssh HOST is ready.'
    if ($pickerReady) { Write-Host 'Run dssh to pick a host. Enable hosts with Tag dalftui in ~/.ssh/config (OpenSSH 9.4+).' }
    else { Write-Host 'Install fzf to enable the picker, or rerun setup without -SkipFzf.' }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        Invoke-DalftuiWindowsSetup -Preference $PackageManager -Skip:$SkipFzf `
            -TargetProfile $ProfilePath -Checkout $PSScriptRoot
    } catch {
        Write-Error ("Setup failed: " + $_.Exception.Message) -ErrorAction Continue
        exit 1
    }
}
