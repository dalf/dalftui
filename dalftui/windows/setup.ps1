#requires -Version 5.1

function Find-DalftuiApplication([string]$Name) {
    Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Test-DalftuiFullyQualifiedWindowsPath([string]$Path) {
    # .NET Framework (PowerShell 5.1) lacks IsPathFullyQualified. Require a
    # drive plus separator, or a UNC/device prefix, before any normalization.
    # IsPathRooted alone also accepts working-directory-dependent C:bin and \bin.
    return (-not [string]::IsNullOrWhiteSpace($Path) -and
        $Path -match '\A(?:[A-Za-z]:[\\/]|[\\/]{2})')
}

function Test-DalftuiFullyQualifiedPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    if ([IO.Path]::DirectorySeparatorChar -eq [char]92) {
        return Test-DalftuiFullyQualifiedWindowsPath $Path
    }
    # Keep the disposable PowerShell tests usable on Linux.
    return [IO.Path]::IsPathRooted($Path)
}

function Get-DalftuiVSCodeCli([string]$Application) {
    $installation = [IO.Path]::GetDirectoryName($Application)
    $launcher = Join-Path $installation 'bin\code.cmd'
    if ([IO.File]::Exists($launcher)) {
        # Read the active version from the installed launcher without executing
        # batch code or guessing among directories left behind by an update.
        $pattern = '(?im)^\s*"%~dp0\.\.[\\/]Code\.exe"\s+"%~dp0\.\.[\\/]' +
            '(?<cli>(?:[0-9a-f]+[\\/])?resources[\\/]app[\\/]out[\\/]cli\.js)"'
        $match = [regex]::Match([IO.File]::ReadAllText($launcher), $pattern)
        if ($match.Success) {
            $relativeCli = $match.Groups['cli'].Value.Replace('\', [IO.Path]::DirectorySeparatorChar)
            return Join-Path $installation $relativeCli
        }
    }
    return Join-Path $installation 'resources\app\out\cli.js'
}

function Resolve-DalftuiVSCode([string]$Path) {
    if (-not (Test-DalftuiFullyQualifiedPath $Path)) {
        throw 'The VS Code installation path must be a fully qualified absolute path.'
    }
    $fullPath = [IO.Path]::GetFullPath($Path)
    if ([IO.Directory]::Exists($fullPath)) {
        $application = Join-Path $fullPath 'Code.exe'
    } else {
        $name = [IO.Path]::GetFileName($fullPath)
        if ($name.Equals('Code.exe', [StringComparison]::OrdinalIgnoreCase)) {
            $application = $fullPath
        } elseif ($name.Equals('code', [StringComparison]::OrdinalIgnoreCase) -or
                  $name.Equals('code.cmd', [StringComparison]::OrdinalIgnoreCase) -or
                  $name.Equals('code.bat', [StringComparison]::OrdinalIgnoreCase)) {
            $bin = [IO.Directory]::GetParent($fullPath)
            if (-not $bin -or -not $bin.Parent) {
                throw "Cannot determine the VS Code installation behind $fullPath."
            }
            $application = Join-Path $bin.Parent.FullName 'Code.exe'
        } else {
            throw "Select the VS Code installation directory, Code.exe, or its bin\code launcher: $fullPath"
        }
    }
    $application = [IO.Path]::GetFullPath($application)
    $cli = Get-DalftuiVSCodeCli $application
    if (-not [IO.File]::Exists($application) -or -not [IO.File]::Exists($cli)) {
        throw "The VS Code installation must contain Code.exe and its active cli.js: $application (CLI: $cli)"
    }
    return $application
}

function Find-DalftuiVSCode([string]$PathValue = $env:PATH) {
    # Do not use Get-Command or Python's shutil.which here. On Windows those can
    # search the process working directory even when it is absent from PATH.
    $currentDirectory = $null
    $location = Get-Location
    if ($location.Provider.Name -eq 'FileSystem') {
        $currentDirectory = [IO.Path]::GetFullPath($location.ProviderPath)
    }
    if ([string]::IsNullOrEmpty($PathValue)) { return $null }
    foreach ($rawEntry in $PathValue.Split([IO.Path]::PathSeparator)) {
        $entry = $rawEntry.Trim().Trim([char]34)
        if (-not (Test-DalftuiFullyQualifiedPath $entry)) {
            continue
        }
        try { $directory = [IO.Path]::GetFullPath($entry) }
        catch { continue }
        $comparisonDirectory = [IO.Path]::GetFullPath((Join-Path $directory '.'))
        if ($currentDirectory) {
            $comparisonCurrent = [IO.Path]::GetFullPath((Join-Path $currentDirectory '.'))
            if ($comparisonDirectory.Equals(
                    $comparisonCurrent, [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
        }
        foreach ($name in @('code.cmd', 'code.bat', 'Code.exe')) {
            $candidate = Join-Path $directory $name
            if (-not [IO.File]::Exists($candidate)) { continue }
            try { return Resolve-DalftuiVSCode $candidate }
            catch { continue }
        }
    }
    return $null
}

function Get-DalftuiVSCodeConfigPath {
    $directory = $env:LOCALAPPDATA
    if (-not (Test-DalftuiFullyQualifiedPath $directory)) {
        $directory = [Environment]::GetFolderPath(
            [Environment+SpecialFolder]::LocalApplicationData)
    }
    if (-not (Test-DalftuiFullyQualifiedPath $directory)) {
        throw 'Cannot determine the local application-data directory for VS Code configuration.'
    }
    return Join-Path $directory 'dalftui\config.json'
}

function Read-DalftuiVSCodeConfig([string]$ConfigPath) {
    if (-not [IO.File]::Exists($ConfigPath)) { return $null }
    try {
        $config = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($ConfigPath))
        return Resolve-DalftuiVSCode ([string]$config.code)
    } catch {
        throw "The configured VS Code installation in $ConfigPath is invalid: $($_.Exception.Message)"
    }
}

function Write-DalftuiVSCodeConfig([string]$ConfigPath, [string]$Application) {
    $application = Resolve-DalftuiVSCode $Application
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($ConfigPath)) | Out-Null
    $json = ConvertTo-Json -Compress -InputObject @{code = $application}
    [IO.File]::WriteAllText($ConfigPath, $json + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false))
}

function Set-DalftuiVSCodeConfiguration([string]$RequestedPath, [string]$ConfigPath) {
    if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
        $ConfigPath = Get-DalftuiVSCodeConfigPath
    }
    $application = $null
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        # Convert only explicit Git Bash drive paths, never PATH/config entries
        # or current-drive-rooted paths such as /bin.
        if ([IO.Path]::DirectorySeparatorChar -eq [char]92 -and
            $RequestedPath -match '\A/([A-Za-z])/(.*)\z') {
            $RequestedPath = $Matches[1] + ':/' + $Matches[2]
        }
        $application = Resolve-DalftuiVSCode $RequestedPath
    } else {
        try { $application = Read-DalftuiVSCodeConfig $ConfigPath }
        catch { Write-Warning $_.Exception.Message }
        if (-not $application) { $application = Find-DalftuiVSCode }
    }
    if (-not $application) {
        Write-Warning ("VS Code was not configured. Install VS Code with its code command on " +
            "an absolute PATH entry, or rerun install.cmd with -VSCodePath for a portable installation.")
        return $null
    }
    Write-DalftuiVSCodeConfig -ConfigPath $ConfigPath -Application $application
    Write-Host "VS Code configured: $application"
    return $application
}

function Get-DalftuiVSCodeSettingsPath([string]$Application) {
    # A data folder next to Code.exe makes VS Code portable, as Scoop installs it.
    $data = Join-Path ([IO.Path]::GetDirectoryName($Application)) 'data'
    if ([IO.Directory]::Exists($data)) { return Join-Path $data 'user-data\User\settings.json' }
    if (-not (Test-DalftuiFullyQualifiedPath $env:APPDATA)) {
        Write-Warning 'APPDATA is not set; the VS Code terminal font was not set.'
        return $null
    }
    return Join-Path $env:APPDATA 'Code\User\settings.json'
}

function Update-DalftuiProcessPath {
    $entries = @($env:PATH,
        [Environment]::GetEnvironmentVariable('PATH', 'User'),
        [Environment]::GetEnvironmentVariable('PATH', 'Machine'))
    $env:PATH = ($entries | Where-Object { $_ }) -join [IO.Path]::PathSeparator
}

function Get-DalftuiProfilePaths([string]$TargetProfile) {
    if (-not [string]::IsNullOrWhiteSpace($TargetProfile)) {
        return $TargetProfile
    }
    $paths = @($PROFILE.CurrentUserCurrentHost)
    # mise and install.cmd can run in 5.1 while Terminal uses PowerShell 7.
    # Ask the other installed shell for its path, including redirected Documents.
    $otherName = 'pwsh'
    if ($PSVersionTable.PSVersion.Major -ge 6) { $otherName = 'powershell' }
    $otherShell = Find-DalftuiApplication $otherName
    if ($otherShell) {
        $previousModulePath = $env:PSModulePath
        try {
            # Windows PowerShell must not inherit PowerShell 7's module paths.
            $env:PSModulePath = $null
            # Base64 avoids native output encoding differences between shells.
            $encoded = & $otherShell.Source -NoLogo -NoProfile -NonInteractive -Command `
                '[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($PROFILE.CurrentUserCurrentHost))'
            if ($LASTEXITCODE -ne 0) { throw "$otherName exited with status $LASTEXITCODE." }
            $path = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($encoded))
            if (-not (Test-DalftuiFullyQualifiedPath $path)) {
                throw 'The shell did not return an absolute profile path.'
            }
            $paths += $path
        } catch {
            throw "Cannot determine the $otherName profile: $($_.Exception.Message) Use -ProfilePath to select a profile explicitly."
        } finally {
            $env:PSModulePath = $previousModulePath
        }
    }
    return $paths | Select-Object -Unique
}

function Write-DalftuiProfile([string]$Path, [string]$Checkout) {
    $Path = [IO.Path]::GetFullPath($Path)
    $loader = Join-Path $Checkout 'bin/profile.ps1'
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

function Remove-DalftuiProfile([string]$Path, [switch]$DryRun) {
    $Path = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Host "No PowerShell profile: $Path"
        return
    }
    $reader = [IO.StreamReader]::new($Path, [Text.Encoding]::Default, $true)
    try { $content = $reader.ReadToEnd(); $encoding = $reader.CurrentEncoding } finally { $reader.Dispose() }
    $starts = [regex]::Matches($content, '(?m)^# >>> dalftui >>>\r?$')
    $ends = [regex]::Matches($content, '(?m)^# <<< dalftui <<<\r?$')
    if (-not ($starts.Count -or $ends.Count)) {
        Write-Host "No dalftui block in PowerShell profile: $Path"
        return
    }
    # Keep the block when it is malformed or holds more than setup's loader line.
    $block = [regex]::Match($content, "(?m)^# >>> dalftui >>>\r?\n\. '(?:[^'\r\n]|'')*\.ps1'\r?\n# <<< dalftui <<<(?:\r?\n|\z)")
    if ($starts.Count -ne 1 -or $ends.Count -ne 1 -or -not $block.Success) {
        Write-Warning "The dalftui block in $Path was edited, incomplete or duplicated; it was left unchanged."
        return
    }
    if ($DryRun) {
        Write-Host "Back up and remove the dalftui block: $Path"
        return
    }
    $backup = $Path + '.dalftui-' + [guid]::NewGuid().ToString('N') + '.bak'
    [IO.File]::Copy($Path, $backup)
    Write-Host "Profile backup: $backup"
    [IO.File]::WriteAllText($Path, $content.Remove($block.Index, $block.Length), $encoding)
    Write-Host "Removed the dalftui block from PowerShell profile: $Path"
}

function Set-DalftuiTerminalShortcut {
    param([string]$Python, [string[]]$PythonArguments, [string]$Checkout,
          [string[]]$SettingsPaths, [string]$PowerShell7, [string]$VSCodeSettingsPath,
          [switch]$Uninstall, [switch]$DryRun)
    # Use the same PowerShell version as setup, without loading personal profiles.
    $shellName = 'powershell.exe'
    if ($PSVersionTable.PSVersion.Major -ge 6) { $shellName = 'pwsh.exe' }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { $shellName = 'pwsh' }
    $shellPath = Join-Path $PSHOME $shellName
    $arguments = @($PythonArguments) + @((Join-Path $Checkout 'bin/terminal_settings.py'), '--shell', $shellPath)
    foreach ($path in $SettingsPaths) { $arguments += @('--settings', $path) }
    if ($PowerShell7) { $arguments += @('--pwsh', $PowerShell7) }
    if ($VSCodeSettingsPath) { $arguments += @('--vscode-settings', $VSCodeSettingsPath) }
    if ($Uninstall) { $arguments += '--uninstall' }
    if ($DryRun) { $arguments += '--dry-run' }
    & $Python @arguments | Out-Host
    if ($LASTEXITCODE -ne 0 -and $Uninstall) { throw 'Some Windows Terminal or VS Code settings were not changed; see the message above.' }
    if ($LASTEXITCODE -ne 0) { throw 'Windows Terminal or VS Code font setup failed; see the message above. dssh is already configured in PowerShell.' }
}

function Test-DalftuiNerdFont {
    # oh-my-posh and Windows register fonts by name under these keys.
    foreach ($hive in @('HKCU:', 'HKLM:')) {
        $fonts = Get-ItemProperty -LiteralPath ($hive + '\Software\Microsoft\Windows NT\CurrentVersion\Fonts') `
            -ErrorAction SilentlyContinue
        # 'Hack Nerd Font Bold (TrueType)', not the Mono or Propo families.
        if ($fonts -and @($fonts.PSObject.Properties.Name -match '^Hack Nerd Font (?!Mono\b|Propo\b)').Count) { return $true }
    }
    return $false
}

function Install-DalftuiNerdFont([string]$OhMyPosh) {
    if (Test-DalftuiNerdFont) {
        Write-Host 'Hack Nerd Font already installed.'
        return
    }
    # Installs for the current user; no administrator rights are needed.
    # A direct release asset avoids the named-font GitHub API lookup, which can
    # fail on shared CI runners before the font download even starts.
    & $OhMyPosh font install 'https://github.com/ryanoasis/nerd-fonts/releases/latest/download/Hack.zip' | Out-Host
    if ($LASTEXITCODE -ne 0 -or -not (Test-DalftuiNerdFont)) {
        throw 'Hack Nerd Font installation failed; see the message above.'
    }
    Write-Host 'Hack Nerd Font installed.'
}

function Test-DalftuiWindowsPlatform {
    return [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
}

function Find-DalftuiPython {
    $python = Find-DalftuiApplication 'py'
    $pythonArguments = @('-3')
    if (-not $python) {
        $python = Find-DalftuiApplication 'python'
        $pythonArguments = @()
    }
    if (-not $python) { throw 'Install Python 3.11+ first, then open a new terminal.' }
    & $python.Source @pythonArguments -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
    return [pscustomobject]@{Source = $python.Source; Arguments = $pythonArguments}
}

function Get-DalftuiInstalledVSCodeSettingsPath([string]$RequestedPath) {
    # Uninstall still finds the settings when VS Code itself was removed.
    $application = $null
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        if ([IO.Path]::DirectorySeparatorChar -eq [char]92 -and
            $RequestedPath -match '\A/([A-Za-z])/(.*)\z') {
            $RequestedPath = $Matches[1] + ':/' + $Matches[2]
        }
        try { $application = Resolve-DalftuiVSCode $RequestedPath }
        catch {
            # A removed VS Code leaves no Code.exe, but its directory may keep portable data.
            if (-not (Test-DalftuiFullyQualifiedPath $RequestedPath) -or
                -not [IO.Directory]::Exists($RequestedPath)) {
                Write-Warning "VS Code settings were not checked: $($_.Exception.Message)"
                return $null
            }
            $application = Join-Path ([IO.Path]::GetFullPath($RequestedPath)) 'Code.exe'
        }
    } else {
        $configPath = Get-DalftuiVSCodeConfigPath
        if ([IO.File]::Exists($configPath)) {
            try { $application = [string](ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($configPath))).code }
            catch { Write-Warning "Ignoring the unreadable $configPath." }
        }
    }
    if (Test-DalftuiFullyQualifiedPath $application) { return Get-DalftuiVSCodeSettingsPath $application }
    if (Test-DalftuiFullyQualifiedPath $env:APPDATA) { return Join-Path $env:APPDATA 'Code\User\settings.json' }
    return $null
}

function Invoke-DalftuiWindowsUninstall {
    param([string]$TargetProfile, [string]$Checkout, [switch]$NoTerminal,
          [string[]]$SettingsPaths, [string]$SelectedVSCodePath, [switch]$DryRun)
    $profilePaths = @(Get-DalftuiProfilePaths -TargetProfile $TargetProfile)
    if (-not $NoTerminal) {
        # Check everything that can fail before changing any profile.
        $python = Find-DalftuiPython
        $vscodeSettings = Get-DalftuiInstalledVSCodeSettingsPath $SelectedVSCodePath
    }
    foreach ($profilePath in $profilePaths) {
        Remove-DalftuiProfile -Path $profilePath -DryRun:$DryRun
    }
    if (-not $NoTerminal) {
        Set-DalftuiTerminalShortcut -Python $python.Source -PythonArguments $python.Arguments `
            -Checkout $Checkout -SettingsPaths $SettingsPaths -VSCodeSettingsPath $vscodeSettings `
            -Uninstall -DryRun:$DryRun
    }
    if ($DryRun) {
        Write-Host 'Dry run: no files changed.'
        return
    }
    Write-Host 'Fonts, Oh My Posh, backups and this checkout were kept.'
    Write-Host 'PowerShell sessions already open keep dssh and Ctrl+Shift+F3 until you open a new session.'
}

function Invoke-DalftuiWindowsSetup {
    [CmdletBinding()]
    param([string]$TargetProfile,
          [string]$Checkout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')),
          [switch]$NoTerminal,
          [string[]]$SettingsPaths, [string]$SelectedVSCodePath,
          [switch]$Uninstall, [switch]$DryRun)
    $ErrorActionPreference = 'Stop'
    if (-not (Test-DalftuiWindowsPlatform)) {
        throw 'This setup script targets Windows. On Linux, use ./install.'
    }
    if ($Uninstall) {
        Invoke-DalftuiWindowsUninstall -TargetProfile $TargetProfile -Checkout $Checkout `
            -NoTerminal:$NoTerminal -SettingsPaths $SettingsPaths `
            -SelectedVSCodePath $SelectedVSCodePath -DryRun:$DryRun
        return
    }
    if ($DryRun) { throw '-DryRun is supported with -Uninstall only.' }
    $profilePaths = @(Get-DalftuiProfilePaths -TargetProfile $TargetProfile)
    $python = Find-DalftuiPython
    $ssh = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
    if (-not (Test-Path -LiteralPath $ssh) -and -not (Find-DalftuiApplication 'ssh')) {
        throw 'Install the Windows OpenSSH client first, then rerun setup.'
    }
    Update-DalftuiProcessPath
    $ohMyPosh = Find-DalftuiApplication 'oh-my-posh'
    if (-not $ohMyPosh) {
        throw 'Install Oh My Posh first (winget install JanDeDobbeleer.OhMyPosh), then rerun setup.'
    }
    $vscode = Set-DalftuiVSCodeConfiguration -RequestedPath $SelectedVSCodePath
    foreach ($profilePath in $profilePaths) {
        Write-DalftuiProfile -Path $profilePath -Checkout $Checkout
    }
    Install-DalftuiNerdFont -OhMyPosh $ohMyPosh.Source
    . (Join-Path $Checkout 'bin/profile.ps1')
    if (-not $NoTerminal) {
        Set-DalftuiTerminalShortcut -Python $python.Source -PythonArguments $python.Arguments `
            -Checkout $Checkout -SettingsPaths $SettingsPaths `
            -PowerShell7 (Find-DalftuiApplication 'pwsh').Source `
            -VSCodeSettingsPath $(if ($vscode) { Get-DalftuiVSCodeSettingsPath $vscode })
    }
    Write-Host 'dssh HOST is ready.'
    Write-Host 'Open a new PowerShell session to load dssh and Ctrl+Shift+F3.'
    Write-Host 'Run dssh to pick a host. Enable hosts with Tag dalftui in ~/.ssh/config (OpenSSH 9.4+).'
    Write-Host 'In the picker, Ctrl+O connects to a typed hostname, IP address or user@host.'
}
