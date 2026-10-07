#requires -Version 5.1
# Standalone assertions: no Pester, package installations, or personal profiles.
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
. (Join-Path $repo 'install.ps1')
$root = Join-Path ([IO.Path]::GetTempPath()) ('dalftui-setup-test-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root) | Out-Null
$checks = 0
function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:checks++
}
function Assert-Throws([scriptblock]$Action, [string]$Message) {
    $thrown = $false
    try { & $Action } catch { $thrown = $true }
    Assert-True $thrown $Message
}
function Copy-DalftuiWindowsCheckout([string]$Source, [string]$Destination) {
    [IO.Directory]::CreateDirectory((Join-Path $Destination 'dalftui\windows')) | Out-Null
    foreach ($file in @('install.cmd', 'install.ps1', 'bin/profile.ps1', 'bin/ssh-tab.ps1',
                         'bin/terminal_settings.py', 'dalftui\__init__.py',
                         'dalftui\windows\__init__.py', 'dalftui\windows\setup.ps1',
                         'dalftui\windows\profile.ps1', 'dalftui\windows\ssh-tab.ps1',
                         'dalftui\windows\terminal_settings.py', 'config\oh-my-posh.omp.json')) {
        $destinationPath = Join-Path $Destination $file
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destinationPath)) | Out-Null
        Copy-Item -LiteralPath (Join-Path $Source $file) -Destination $destinationPath
    }
}
function ConvertTo-DalftuiSingleQuotedLiteral([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}
try {
    foreach ($function in @('Find-DalftuiApplication', 'Write-DalftuiProfile',
                             'Set-DalftuiTerminalShortcut', 'Invoke-DalftuiWindowsSetup')) {
        Assert-True (Test-Path -LiteralPath ("Function:\" + $function)) `
            "Dot-sourcing root install.ps1 must expose $function without running setup"
    }
    foreach ($file in @('install.ps1', 'bin/profile.ps1', 'bin/ssh-tab.ps1',
                         'dalftui\windows\setup.ps1', 'dalftui\windows\profile.ps1',
                         'dalftui\windows\ssh-tab.ps1')) {
        $parseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo $file),
            [ref]$null, [ref]$parseErrors) | Out-Null
        Assert-True (-not $parseErrors) "$file must parse in this PowerShell version"
    }

    # Exercise the public setup command in a child process with a harmless
    # implementation probe. This covers parameter binding, arrays, switches,
    # effective defaults, checkout forwarding, and failure status handling.
    $forwardingCheckout = Join-Path $root ("forwarding checkout's " + [char]0xe9)
    Copy-DalftuiWindowsCheckout -Source $repo -Destination $forwardingCheckout
    $probeImplementation = @'
function Invoke-DalftuiWindowsSetup {
    [CmdletBinding()]
    param([string]$TargetProfile,
          [string]$Checkout, [switch]$NoTerminal, [string[]]$SettingsPaths,
          [string]$SelectedVSCodePath, [switch]$Uninstall, [switch]$DryRun)
    if ($env:DALFTUI_SETUP_PROBE_FAIL) { throw 'probe failure' }
    $result = [ordered]@{
        TargetProfile = $TargetProfile
        Checkout = $Checkout
        NoTerminal = [bool]$NoTerminal
        Uninstall = [bool]$Uninstall
        DryRun = [bool]$DryRun
        SettingsPaths = @($SettingsPaths)
        SelectedVSCodePath = $SelectedVSCodePath
        ProcessPolicy = (Get-ExecutionPolicy -Scope Process).ToString()
    }
    [IO.File]::WriteAllText($env:DALFTUI_SETUP_PROBE,
        (ConvertTo-Json -Compress -Depth 3 -InputObject $result),
        [Text.UTF8Encoding]::new($false))
}
'@
    [IO.File]::WriteAllText((Join-Path $forwardingCheckout 'dalftui\windows\setup.ps1'),
        $probeImplementation, [Text.UTF8Encoding]::new($true))
    $unrelated = Join-Path $root 'unrelated working directory'
    [IO.Directory]::CreateDirectory($unrelated) | Out-Null
    $probeLog = Join-Path $root 'setup-forwarding.json'
    $runner = Join-Path $root 'setup-forwarding-runner.ps1'
    $targetProfile = Join-Path $root ("profile target's " + [char]0xe9 + '.ps1')
    $selectedCode = Join-Path $root ("VS Code portable's " + [char]0xe9)
    $settingsOne = Join-Path $root 'Terminal stable settings.json'
    $settingsTwo = Join-Path $root ("Terminal preview's " + [char]0xe9 + '.json')
    $wrapperLiteral = ConvertTo-DalftuiSingleQuotedLiteral `
        (Join-Path $forwardingCheckout 'install.ps1')
    # Group concatenations so commas separate lines instead of joining operands.
    $runnerLines = @(
        '$ErrorActionPreference = ''Stop''',
        ('Push-Location -LiteralPath ' + (ConvertTo-DalftuiSingleQuotedLiteral $unrelated)),
        'try {',
        ('    & ' + $wrapperLiteral +
            ' -VSCodePath ' + (ConvertTo-DalftuiSingleQuotedLiteral $selectedCode) +
            ' -ProfilePath ' + (ConvertTo-DalftuiSingleQuotedLiteral $targetProfile) +
            ' -SkipTerminal -TerminalSettingsPath @(' +
            (ConvertTo-DalftuiSingleQuotedLiteral $settingsOne) + ', ' +
            (ConvertTo-DalftuiSingleQuotedLiteral $settingsTwo) + ')'),
        '} finally { Pop-Location }',
        'exit $LASTEXITCODE'
    )
    [IO.File]::WriteAllLines($runner, $runnerLines, [Text.UTF8Encoding]::new($true))
    $probeShellName = 'powershell.exe'
    if ($PSVersionTable.PSVersion.Major -ge 6) { $probeShellName = 'pwsh.exe' }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { $probeShellName = 'pwsh' }
    $probeShell = Join-Path $PSHOME $probeShellName
    $env:DALFTUI_SETUP_PROBE = $probeLog
    $null = & $probeShell -NoLogo -NoProfile -File $runner
    Assert-True ($LASTEXITCODE -eq 0) 'The public setup wrapper must forward non-default arguments successfully'
    $forwarded = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($probeLog))
    Assert-True ($forwarded.TargetProfile -eq $targetProfile -and $forwarded.NoTerminal -and
                 $forwarded.SelectedVSCodePath -eq $selectedCode) `
        'The public setup wrapper must preserve non-default scalar and switch arguments'
    Assert-True ($forwarded.Checkout -eq $forwardingCheckout) `
        'Setup must resolve the copied checkout independently of the working directory'
    Assert-True ($forwarded.SettingsPaths.Count -eq 2 -and
                 $forwarded.SettingsPaths[0] -eq $settingsOne -and
                 $forwarded.SettingsPaths[1] -eq $settingsTwo) `
        'The public setup wrapper must preserve TerminalSettingsPath arrays'

    [IO.File]::WriteAllLines($runner, @(('& ' + $wrapperLiteral), 'exit $LASTEXITCODE'),
        [Text.UTF8Encoding]::new($true))
    $null = & $probeShell -NoLogo -NoProfile -File $runner
    Assert-True ($LASTEXITCODE -eq 0) 'The public setup wrapper must forward defaults successfully'
    $forwarded = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($probeLog))
    Assert-True (-not $forwarded.NoTerminal -and -not $forwarded.TargetProfile -and
                 $forwarded.Checkout -eq $forwardingCheckout) `
        'The public setup wrapper must leave profile discovery to the installer by default'
    Assert-True (-not $forwarded.Uninstall -and -not $forwarded.DryRun) 'Setup must not uninstall by default'
    [IO.File]::WriteAllLines($runner, @(('& ' + $wrapperLiteral + ' -Uninstall -DryRun -SkipTerminal'),
        'exit $LASTEXITCODE'), [Text.UTF8Encoding]::new($true))
    $null = & $probeShell -NoLogo -NoProfile -File $runner
    $forwarded = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($probeLog))
    Assert-True ($LASTEXITCODE -eq 0 -and $forwarded.Uninstall -and $forwarded.DryRun -and $forwarded.NoTerminal) `
        'The public setup wrapper must forward -Uninstall and -DryRun'
    [IO.File]::WriteAllLines($runner, @(('& ' + $wrapperLiteral), 'exit $LASTEXITCODE'),
        [Text.UTF8Encoding]::new($true))
    $env:DALFTUI_SETUP_PROBE_FAIL = '1'
    # Windows PowerShell 5.1 turns captured native stderr into error records.
    # Allow the expected failure output while still checking its exit status.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $failureOutput = & $probeShell -NoLogo -NoProfile -File $runner 2>&1
        $failureExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    Assert-True ($failureExitCode -eq 1) 'A setup implementation failure must return status 1'
    Assert-True (($failureOutput | Out-String).Contains('Setup failed: probe failure')) `
        'A setup implementation failure must retain the Setup failed message'
    Remove-Item Env:\DALFTUI_SETUP_PROBE_FAIL
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        # Exercise the CMD installer through the renamed PowerShell entrypoint
        # in a copied checkout, without touching any real profile or packages.
        $cmdInstaller = Join-Path $forwardingCheckout 'install.cmd'
        $modulePathBefore = $env:PSModulePath
        Push-Location -LiteralPath $unrelated
        try {
            $null = & $cmdInstaller `
                -VSCodePath $selectedCode -ProfilePath $targetProfile -SkipTerminal `
                -TerminalSettingsPath $settingsOne
            Assert-True ($LASTEXITCODE -eq 0) 'install.cmd must preserve successful setup status'
            $forwarded = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($probeLog))
            Assert-True ($forwarded.Checkout -eq $forwardingCheckout -and
                         $forwarded.TargetProfile -eq $targetProfile -and $forwarded.NoTerminal -and
                         $forwarded.SelectedVSCodePath -eq $selectedCode -and
                         $forwarded.SettingsPaths[0] -eq $settingsOne) `
                'install.cmd must locate install.ps1 and preserve options from another directory'
            Assert-True ($forwarded.ProcessPolicy -eq 'Bypass') `
                'install.cmd must set the bypass policy for its child process'
            # An empty environment value can become absent across CMD on Windows.
            Assert-True ([string]$env:PSModulePath -eq [string]$modulePathBefore) `
                'install.cmd must preserve the calling shell module paths'
            $env:DALFTUI_SETUP_PROBE_FAIL = '1'
            $ErrorActionPreference = 'Continue'
            $failureOutput = & $cmdInstaller 2>&1
            $failureExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
            Remove-Item Env:\DALFTUI_SETUP_PROBE_FAIL -ErrorAction SilentlyContinue
            Pop-Location
        }
        Assert-True ($failureExitCode -eq 1) 'install.cmd must preserve failed setup status'
        Assert-True (($failureOutput | Out-String).Contains('Setup failed: probe failure')) `
            'install.cmd must retain the setup failure message'
    }
    Remove-Item Env:\DALFTUI_SETUP_PROBE

    # Check Windows qualification semantics on every platform; IsPathRooted
    # would incorrectly accept drive-relative and current-drive-rooted paths.
    foreach ($path in @('', ' ', 'bin', '.\bin', '..\bin', 'C:', 'C:bin', 'C:.\bin', '\bin', '/bin')) {
        Assert-True (-not (Test-DalftuiFullyQualifiedWindowsPath $path)) "Windows path must be rejected before normalization: $path"
    }
    foreach ($path in @('C:\Tools\Code', 'C:/Tools/Code', '\\server\share\Code',
                         '//server/share/Code', '\\?\C:\Tools\Code', '\\?\UNC\server\share\Code')) {
        Assert-True (Test-DalftuiFullyQualifiedWindowsPath $path) "Fully qualified Windows path must be accepted: $path"
    }

    # VS Code discovery must inspect only explicit absolute PATH directories.
    # In particular, neither Windows' implicit current-directory lookup nor an
    # empty/relative PATH component may select a project-controlled Code.exe.
    $project = Join-Path $root 'untrusted project'
    $fakeCli = Join-Path $project 'resources\app\out\cli.js'
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($fakeCli)) | Out-Null
    [IO.File]::WriteAllText((Join-Path $project 'Code.exe'), '')
    [IO.File]::WriteAllText($fakeCli, '')
    $fakeBin = Join-Path $project 'bin'
    [IO.Directory]::CreateDirectory($fakeBin) | Out-Null
    [IO.File]::WriteAllText((Join-Path $fakeBin 'code.cmd'), '')
    $ordinaryBin = Join-Path $root 'ordinary absolute bin'
    [IO.Directory]::CreateDirectory($ordinaryBin) | Out-Null
    $portable = Join-Path $root ("portable VS Code spaces " + [char]0xe9)
    $portableBin = Join-Path $portable 'bin'
    $portableCli = Join-Path $portable 'resources\app\out\cli.js'
    [IO.Directory]::CreateDirectory($portableBin) | Out-Null
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($portableCli)) | Out-Null
    [IO.File]::WriteAllText((Join-Path $portable 'Code.exe'), '')
    [IO.File]::WriteAllText((Join-Path $portableBin 'code.cmd'), '')
    [IO.File]::WriteAllText($portableCli, '')
    Push-Location -LiteralPath $project
    try {
        Assert-True ($null -eq (Find-DalftuiVSCode $ordinaryBin)) 'An ordinary absolute PATH must not search the current directory'
        Assert-True ($null -eq (Find-DalftuiVSCode $project)) 'Even an absolute PATH entry equal to the current project must be excluded'
        $unsafeEntries = @('', '.', 'relative-bin', $ordinaryBin, '') -join [IO.Path]::PathSeparator
        Assert-True ($null -eq (Find-DalftuiVSCode $unsafeEntries)) 'Empty and relative PATH entries must not search the current directory'
        $mixedEntries = @('', '.', 'relative-bin', $ordinaryBin, $portableBin) -join [IO.Path]::PathSeparator
        $found = Find-DalftuiVSCode $mixedEntries
        Assert-True ($found -eq (Join-Path $portable 'Code.exe')) 'Discovery must find a valid installation only in an absolute PATH directory'
        if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
            # Match the process and PowerShell directories so Windows resolves
            # the rejected entries to the real fake installation above.
            $previousDirectory = [Environment]::CurrentDirectory
            $previousLocalAppData = $env:LOCALAPPDATA
            $knownLocalAppData = [Environment]::GetFolderPath(
                [Environment+SpecialFolder]::LocalApplicationData)
            try {
                [Environment]::CurrentDirectory = $project
                $drive = [IO.Path]::GetPathRoot($project).Substring(0, 2)
                $relativeEntries = @(($drive + 'bin'), ($drive + '.\bin'), $fakeBin.Substring(2),
                                     $fakeBin.Substring(2).Replace('\', '/'))
                foreach ($entry in $relativeEntries) {
                    Assert-True ([IO.Path]::IsPathRooted($entry)) "Regression fixture must exercise a rooted relative path: $entry"
                    Assert-True (([IO.Path]::GetFullPath($entry)).Equals(
                        [IO.Path]::GetFullPath($fakeBin), [StringComparison]::OrdinalIgnoreCase)) 'Rejected PATH fixture must resolve to the fake installation directory'
                    Assert-True ($null -eq (Find-DalftuiVSCode $entry)) "Rooted relative PATH must not select the project executable: $entry"
                    $mixedEntries = @($entry, $portableBin) -join [IO.Path]::PathSeparator
                    Assert-True ((Find-DalftuiVSCode $mixedEntries) -eq (Join-Path $portable 'Code.exe')) 'Rejected entries must not hide a later trusted installation'
                }
                foreach ($entry in @(($drive + 'Code.exe'), ($drive + '.\Code.exe'),
                                     (Join-Path $project 'Code.exe').Substring(2))) {
                    Assert-True ([IO.File]::Exists([IO.Path]::GetFullPath($entry))) 'Rejected explicit-path fixture must point to the existing fake executable'
                    Assert-Throws { Resolve-DalftuiVSCode $entry } "Explicit rooted relative executable must be rejected: $entry"
                }
                $unwrittenConfig = Join-Path $root 'rejected-config.json'
                Assert-Throws { Set-DalftuiVSCodeConfiguration -RequestedPath ($drive + 'Code.exe') -ConfigPath $unwrittenConfig } 'Rejected installation must not be persisted'
                Assert-True (-not [IO.File]::Exists($unwrittenConfig)) 'Rejected installation must leave no configuration file'
                $env:LOCALAPPDATA = $drive + 'local-app-data'
                Assert-True ((Get-DalftuiVSCodeConfigPath) -eq (Join-Path $knownLocalAppData 'dalftui\config.json')) 'A rooted relative application-data directory must use the Windows known-folder fallback'
            } finally {
                [Environment]::CurrentDirectory = $previousDirectory
                $env:LOCALAPPDATA = $previousLocalAppData
            }
        }
    } finally { Pop-Location }
    Assert-Throws { Resolve-DalftuiVSCode '.\portable' } 'An explicit portable installation must use an absolute path'
    Assert-True ((Resolve-DalftuiVSCode $portable) -eq (Join-Path $portable 'Code.exe')) 'An explicit portable installation with spaces and Unicode must work'
    $editorConfig = Join-Path $root 'local app data\dalftui\config.json'
    Write-DalftuiVSCodeConfig -ConfigPath $editorConfig -Application $portable
    Assert-True ((Read-DalftuiVSCodeConfig $editorConfig) -eq (Join-Path $portable 'Code.exe')) 'Setup must persist and reuse the absolute Code.exe path'
    Assert-True ((Set-DalftuiVSCodeConfiguration -ConfigPath $editorConfig) -eq (Join-Path $portable 'Code.exe')) 'Repeated setup must prefer the configured installation over discovery'
    $configuredJson = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($editorConfig))
    Assert-True (Test-DalftuiFullyQualifiedPath ([string]$configuredJson.code)) 'The persisted VS Code path must be fully qualified'
    $previousAppData = $env:APPDATA
    try {
        $portableApp = Join-Path $portable 'Code.exe'
        $env:APPDATA = Join-Path $root 'roaming'
        Assert-True ((Get-DalftuiVSCodeSettingsPath $portableApp) -eq (Join-Path $env:APPDATA 'Code\User\settings.json')) 'An installed VS Code must use its roaming settings'
        $portableData = Join-Path $portable 'data'
        [IO.Directory]::CreateDirectory($portableData) | Out-Null
        Assert-True ((Get-DalftuiVSCodeSettingsPath $portableApp) -eq (Join-Path $portableData 'user-data\User\settings.json')) 'A portable VS Code must use the settings in its data folder'
        [IO.Directory]::Delete($portableData)
        $env:APPDATA = ''
        Assert-True ($null -eq (Get-DalftuiVSCodeSettingsPath $portableApp 3>$null)) 'Without APPDATA, setup must not guess the VS Code settings'
    } finally { $env:APPDATA = $previousAppData }

    [IO.File]::WriteAllText((Join-Path $portableBin 'code'), '')
    Assert-True ((Resolve-DalftuiVSCode (Join-Path $portableBin 'code')) -eq (Join-Path $portable 'Code.exe')) 'The Git Bash launcher must resolve to the installation executable'
    if ([IO.Path]::DirectorySeparatorChar -eq [char]92) {
        $bashPath = '/' + $portable.Substring(0, 1).ToLowerInvariant() +
            $portable.Substring(2).Replace('\', '/') + '/bin/code'
        Assert-True (-not (Test-DalftuiFullyQualifiedWindowsPath $bashPath)) 'Git Bash syntax must not relax PATH discovery rules'
        Assert-True ((Set-DalftuiVSCodeConfiguration -RequestedPath $bashPath -ConfigPath $editorConfig) -eq
            (Join-Path $portable 'Code.exe')) 'An explicit Git Bash path must configure the selected installation'
        $configuredJson = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($editorConfig))
        Assert-True ($configuredJson.code -eq (Join-Path $portable 'Code.exe')) 'Git Bash paths must be persisted as fully qualified Windows executable paths'
        Assert-Throws { Set-DalftuiVSCodeConfiguration -RequestedPath '/bin/code' -ConfigPath $editorConfig } 'Current-drive-rooted paths must still be rejected'
    }

    # Model an update leaving both a flat tree and multiple version directories.
    $versioned = Join-Path $root 'versioned VS Code'
    $versionedApp = Join-Path $versioned 'Code.exe'
    $versionedBin = Join-Path $versioned 'bin'
    [IO.Directory]::CreateDirectory($versionedBin) | Out-Null
    [IO.File]::WriteAllText($versionedApp, '')
    $versionedLauncher = Join-Path $versionedBin 'code.cmd'
    foreach ($version in @('', '04c0d99f4f', '07f806f999')) {
        $versionCli = Join-Path (Join-Path $versioned $version) 'resources\app\out\cli.js'
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($versionCli)) | Out-Null
        [IO.File]::WriteAllText($versionCli, '')
    }
    foreach ($version in @('04c0d99f4f', '07f806f999')) {
        $versionCli = Join-Path (Join-Path $versioned $version) 'resources\app\out\cli.js'
        $launcherText = '@echo off' + [Environment]::NewLine +
            '"%~dp0..\Code.exe" "%~dp0..\' + $version + '\resources\app\out\cli.js" %*'
        [IO.File]::WriteAllText($versionedLauncher, $launcherText)
        Assert-True ((Get-DalftuiVSCodeCli $versionedApp) -eq $versionCli) 'The installed launcher must select the active CLI, including after an update'
        Assert-True ((Find-DalftuiVSCode $versionedBin) -eq $versionedApp) 'PATH discovery must support versioned installations'
        Assert-True ((Set-DalftuiVSCodeConfiguration -RequestedPath $versionedApp -ConfigPath $editorConfig) -eq $versionedApp) 'Setup must accept versioned installations'
    }
    [IO.File]::Delete($versionCli)
    Assert-Throws { Resolve-DalftuiVSCode $versionedApp } 'A missing active CLI must not fall back to an old flat tree or another version'
    Assert-True ($null -eq (Find-DalftuiVSCode $versionedBin)) 'Discovery must reject an installation with a missing active CLI'

    $outsideCli = Join-Path $root 'resources\app\out\cli.js'
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($outsideCli)) | Out-Null
    [IO.File]::WriteAllText($outsideCli, '')
    [IO.File]::Delete((Join-Path $versioned 'resources\app\out\cli.js'))
    [IO.File]::WriteAllText($versionedLauncher,
        '"%~dp0..\Code.exe" "%~dp0..\..\resources\app\out\cli.js" %*')
    Assert-Throws { Resolve-DalftuiVSCode $versionedApp } 'The launcher must not select CLI paths outside the installation'

    # Profile discovery is read-only, even when both real shells are installed.
    $nativeProfiles = @(Get-DalftuiProfilePaths)
    Assert-True ($nativeProfiles -contains $PROFILE.CurrentUserCurrentHost) `
        'Default setup must include the shell running the installer'
    $otherShellName = 'pwsh'
    if ($PSVersionTable.PSVersion.Major -ge 6) { $otherShellName = 'powershell' }
    if (Find-DalftuiApplication $otherShellName) {
        Assert-True ($nativeProfiles.Count -eq 2) `
            'Default setup must discover both installed PowerShell profiles'
    }
    $otherProfile = Join-Path $root ("redirected Documents's " + [char]0xe9 + '/PowerShell/Microsoft.PowerShell_profile.ps1')
    $fakeShell = Join-Path $root 'profile-shell.ps1'
    $shellProbe = @(
        'param([switch]$NoLogo, [switch]$NoProfile, [switch]$NonInteractive, [string]$Command)',
        'if (-not ($NoLogo -and $NoProfile -and $NonInteractive)) { throw ''Profile discovery must not load profiles or prompt.'' }',
        'if ($env:PSModulePath) { throw ''Profile discovery must reset inherited module paths.'' }',
        ('[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes(' + (ConvertTo-DalftuiSingleQuotedLiteral $otherProfile) + '))'),
        '$global:LASTEXITCODE = 0'
    )
    [IO.File]::WriteAllLines($fakeShell, $shellProbe, [Text.UTF8Encoding]::new($true))
    & {
        function Find-DalftuiApplication([string]$Name) { throw 'Explicit profiles must skip shell discovery.' }
        $explicit = @(Get-DalftuiProfilePaths -TargetProfile $otherProfile)
        Assert-True ($explicit.Count -eq 1 -and $explicit[0] -eq $otherProfile) `
            'An explicit ProfilePath must target only that file'
        function Find-DalftuiApplication([string]$Name) { return $null }
        $single = @(Get-DalftuiProfilePaths)
        Assert-True ($single.Count -eq 1 -and $single[0] -eq $PROFILE.CurrentUserCurrentHost) `
            'Setup must work when only its own PowerShell version is installed'
        function Find-DalftuiApplication([string]$Name) {
            Assert-True ($Name -eq $otherShellName) 'Discovery must query the other PowerShell version'
            return [pscustomobject]@{Source = $fakeShell}
        }
        $modulePathBefore = $env:PSModulePath
        $discovered = @(Get-DalftuiProfilePaths)
        Assert-True ($discovered.Count -eq 2 -and $discovered[1] -eq $otherProfile) `
            'Discovery must preserve redirected profile paths with spaces, apostrophes, and Unicode'
        Assert-True ([string]$env:PSModulePath -eq [string]$modulePathBefore) `
            'Profile discovery must restore the installer module paths'
        [IO.File]::WriteAllText($fakeShell, '$global:LASTEXITCODE = 17')
        Assert-Throws { Get-DalftuiProfilePaths } 'A failed profile query must fail setup visibly'
        Assert-True ([string]$env:PSModulePath -eq [string]$modulePathBefore) `
            'A failed profile query must still restore module paths'
    }

    # The moved implementation must derive its default checkout from its own
    # package location when callers invoke the setup function directly.
    $pythonCommand = Get-Command py -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command python -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
    }
    $pythonCommandName = [IO.Path]::GetFileNameWithoutExtension($pythonCommand.Name)
    $script:directSetupCheckout = $null
    $previousSystemRoot = $env:SystemRoot
    try {
        if (-not $env:SystemRoot) { $env:SystemRoot = [IO.Path]::GetPathRoot($root) }
        & {
            function Test-DalftuiWindowsPlatform { return $true }
            function Find-DalftuiApplication([string]$Name) {
                Assert-True ($Name -notin @('fzf', 'winget', 'choco')) `
                    'Setup must not look for an external picker or package manager'
                if ($Name -eq $pythonCommandName) { return $pythonCommand }
                if ($Name -eq 'ssh') {
                    return [pscustomobject]@{Name = 'ssh'; Source = 'ssh'}
                }
                if ($Name -eq 'oh-my-posh' -and -not $script:missingOhMyPosh) {
                    return [pscustomobject]@{Name = 'oh-my-posh'; Source = 'fake-oh-my-posh'}
                }
                if ($Name -eq 'pwsh') { return [pscustomobject]@{Name = 'pwsh'; Source = 'fake-pwsh'} }
                return $null
            }
            function Update-DalftuiProcessPath {}
            function Install-DalftuiNerdFont([string]$OhMyPosh) { $script:fontInstaller = $OhMyPosh }
            function Set-DalftuiVSCodeConfiguration([string]$RequestedPath, [string]$ConfigPath) {
                return $null
            }
            function Write-DalftuiProfile([string]$Path, [string]$Checkout) {
                $script:directSetupCheckout = $Checkout
            }
            Invoke-DalftuiWindowsSetup -TargetProfile (Join-Path $root 'direct profile.ps1') `
                -NoTerminal -WarningAction SilentlyContinue
            Assert-True ($script:fontInstaller -eq 'fake-oh-my-posh') `
                'Setup must install the Hack Nerd Font with the discovered oh-my-posh'
            $script:missingOhMyPosh = $true
            $script:directSetupCheckout = $null
            $message = ''
            try {
                Invoke-DalftuiWindowsSetup -TargetProfile (Join-Path $root 'direct profile.ps1') `
                    -NoTerminal -WarningAction SilentlyContinue
            } catch { $message = $_.Exception.Message }
            Assert-True ($message.Contains('winget install JanDeDobbeleer.OhMyPosh') -and
                         $null -eq $script:directSetupCheckout) `
                'Setup must require oh-my-posh before changing any profile'
            $script:missingOhMyPosh = $false
            Invoke-DalftuiWindowsSetup -TargetProfile (Join-Path $root 'direct profile.ps1') `
                -NoTerminal -WarningAction SilentlyContinue
            function Set-DalftuiTerminalShortcut([string]$Python, [string[]]$PythonArguments,
                    [string]$Checkout, [string[]]$SettingsPaths, [string]$PowerShell7,
                    [string]$VSCodeSettingsPath) {
                $script:terminalPwsh = $PowerShell7
                $script:vscodeSettings = $VSCodeSettingsPath
            }
            Invoke-DalftuiWindowsSetup -TargetProfile (Join-Path $root 'direct profile.ps1') `
                -WarningAction SilentlyContinue
            Assert-True ($script:terminalPwsh -eq 'fake-pwsh') `
                'Setup must pass the discovered PowerShell 7 to the Terminal profiles'
            Assert-True (-not $script:vscodeSettings) 'Without VS Code, setup must not pass VS Code settings'
            function Set-DalftuiVSCodeConfiguration([string]$RequestedPath, [string]$ConfigPath) {
                return 'fake Code.exe'
            }
            function Get-DalftuiVSCodeSettingsPath([string]$Application) { return "settings of $Application" }
            Invoke-DalftuiWindowsSetup -TargetProfile (Join-Path $root 'direct profile.ps1') `
                -WarningAction SilentlyContinue
            Assert-True ($script:vscodeSettings -eq 'settings of fake Code.exe') `
                'Setup must pass the configured VS Code settings to the font setup'
            Remove-Item Function:\Set-DalftuiTerminalShortcut

            # Run default installation twice against disposable profiles. Keep
            # real discovery separate so these tests never edit personal files.
            Remove-Item Function:\Write-DalftuiProfile
            $defaultWindowsProfile = Join-Path $root 'WindowsPowerShell/Microsoft.PowerShell_profile.ps1'
            $defaultPwshProfile = Join-Path $root 'PowerShell/Microsoft.PowerShell_profile.ps1'
            function Get-DalftuiProfilePaths([string]$TargetProfile) {
                Assert-True (-not $TargetProfile) 'Default setup must not restrict discovery to its own profile'
                return @($defaultWindowsProfile, $defaultPwshProfile)
            }
            Invoke-DalftuiWindowsSetup -NoTerminal -WarningAction SilentlyContinue
            Invoke-DalftuiWindowsSetup -NoTerminal -WarningAction SilentlyContinue
            foreach ($installedProfile in @($defaultWindowsProfile, $defaultPwshProfile)) {
                $installedText = [IO.File]::ReadAllText($installedProfile)
                Assert-True ([regex]::Matches($installedText, '(?m)^# >>> dalftui >>>').Count -eq 1) `
                    'Default installation must configure each PowerShell profile exactly once'
                . $installedProfile
                $editorHandlers = @(Get-PSReadLineKeyHandler | Where-Object { $_.Function -eq 'DalftuiOpenFolderInCode' })
                Assert-True ($editorHandlers.Count -eq 2) `
                    'Each installed profile must load the native and translated Ctrl+Shift+F3 handlers'
                Assert-True (@(Get-ChildItem -LiteralPath (Split-Path $installedProfile) -Filter '*.bak').Count -eq 0) `
                    'Repeating default setup must leave configured profiles unchanged'
            }
        }
    } finally {
        $env:SystemRoot = $previousSystemRoot
    }
    Assert-True ($script:directSetupCheckout -eq [IO.Path]::GetFullPath($repo)) `
        'Direct Invoke-DalftuiWindowsSetup must default to the actual checkout root'

    $checkout = Join-Path $root ("repo's unicode " + [char]0xe9)
    Copy-DalftuiWindowsCheckout -Source $repo -Destination $checkout
    # Install the font only when it is absent, and check the result.
    $fakeOhMyPosh = Join-Path $root 'fake-oh-my-posh.ps1'
    $fontLog = Join-Path $root 'font-install.txt'
    [IO.File]::WriteAllLines($fakeOhMyPosh, @(
        ('[IO.File]::WriteAllText(' + (ConvertTo-DalftuiSingleQuotedLiteral $fontLog) + ', ($args -join '' ''))'),
        '$global:dalftuiFontInstalled = $true',
        '$global:LASTEXITCODE = 0'), [Text.UTF8Encoding]::new($true))
    & {
        $global:dalftuiFontInstalled = $true
        function Test-DalftuiNerdFont { return $global:dalftuiFontInstalled }
        Install-DalftuiNerdFont -OhMyPosh $fakeOhMyPosh
        Assert-True (-not [IO.File]::Exists($fontLog)) 'An installed Hack Nerd Font must not be reinstalled'
        $global:dalftuiFontInstalled = $false
        Install-DalftuiNerdFont -OhMyPosh $fakeOhMyPosh
        Assert-True ([IO.File]::ReadAllText($fontLog) -eq `
                     'font install https://github.com/ryanoasis/nerd-fonts/releases/latest/download/Hack.zip') `
            'A missing Hack Nerd Font must use the direct official asset URL, avoiding GitHub API discovery'
        [IO.File]::WriteAllText($fakeOhMyPosh, '$global:LASTEXITCODE = 0')
        $global:dalftuiFontInstalled = $false
        Assert-Throws { Install-DalftuiNerdFont -OhMyPosh $fakeOhMyPosh } `
            'A font installation that leaves the font missing must fail setup'
    }
    & {
        function Get-ItemProperty { return $global:dalftuiRegisteredFonts }
        $global:dalftuiRegisteredFonts = [pscustomobject]@{
            'Hack Nerd Font Mono Regular (TrueType)' = 'HackNerdFontMono-Regular.ttf'
            'Hack Nerd Font Propo Bold (TrueType)' = 'HackNerdFontPropo-Bold.ttf' }
        Assert-True (-not (Test-DalftuiNerdFont)) 'Only the Mono or Propo family must not count as Hack Nerd Font'
        $global:dalftuiRegisteredFonts = [pscustomobject]@{
            'Hack Nerd Font Regular (TrueType)' = 'HackNerdFont-Regular.ttf' }
        Assert-True (Test-DalftuiNerdFont) 'A registered Hack Nerd Font must be detected'
    }

    $profile = Join-Path (Join-Path $root 'profile directory') 'profile.ps1'
    Write-DalftuiProfile -Path $profile -Checkout $checkout
    Assert-True (Test-Path -LiteralPath $profile) 'A missing profile and parent directory must be created'
    $parseErrors = $null
    [Management.Automation.Language.Parser]::ParseFile($profile, [ref]$null, [ref]$parseErrors) | Out-Null
    Assert-True (-not $parseErrors) 'Checkout apostrophes and Unicode must form a valid profile'
    $bytes = [IO.File]::ReadAllBytes($profile)
    Write-DalftuiProfile -Path $profile -Checkout $checkout
    Assert-True ([Convert]::ToBase64String($bytes) -eq [Convert]::ToBase64String([IO.File]::ReadAllBytes($profile))) 'Repeated setup must leave the profile bytes unchanged'
    Assert-True (@(Get-ChildItem -LiteralPath (Split-Path $profile) -Filter '*.bak').Count -eq 0) 'Repeated setup must avoid unnecessary backups'

    # Preserve existing UTF-16 text and append the managed loader after an old dssh.
    $existing = "# personal " + [char]0xe9 + "`r`nfunction dssh { 'old' }`r`n"
    [IO.File]::WriteAllText($profile, $existing, [Text.Encoding]::Unicode)
    $before = [IO.File]::ReadAllBytes($profile)
    Write-DalftuiProfile -Path $profile -Checkout $checkout
    $content = [IO.File]::ReadAllText($profile)
    Assert-True ($content.StartsWith($existing)) 'Existing profile text and line endings must be preserved'
    $backups = @(Get-ChildItem -LiteralPath (Split-Path $profile) -Filter '*.bak')
    Assert-True ($backups.Count -eq 1) 'A changed existing profile must have one backup'
    Assert-True ([Convert]::ToBase64String($before) -eq [Convert]::ToBase64String([IO.File]::ReadAllBytes($backups[0].FullName))) 'Backup must preserve the original profile bytes'
    Write-DalftuiProfile -Path $profile -Checkout $checkout
    Assert-True ([regex]::Matches([IO.File]::ReadAllText($profile), '(?m)^# >>> dalftui >>>').Count -eq 1) 'Rerunning setup must not duplicate its block'
    $moved = Join-Path $root 'moved checkout'
    Copy-DalftuiWindowsCheckout -Source $repo -Destination $moved
    Write-DalftuiProfile -Path $profile -Checkout $moved
    Assert-True ([IO.File]::ReadAllText($profile).Contains($moved)) 'Rerunning from a moved checkout must update the loader'
    Assert-True ([IO.File]::ReadAllText($profile).StartsWith($existing)) 'Moving a checkout must preserve personal settings'
    [IO.File]::WriteAllText($profile, '# >>> dalftui >>>')
    Assert-Throws { Write-DalftuiProfile -Path $profile -Checkout $checkout } 'An incomplete block must not be overwritten'
    Assert-True ([IO.File]::ReadAllText($profile) -eq '# >>> dalftui >>>') 'Malformed profile must remain untouched'

    # Exercise the installed profile -> bin launcher -> profile implementation
    # without SSH or a GUI.
    [IO.File]::WriteAllText((Join-Path $checkout 'bin/ssh_picker.py'), 'import json, sys; print(json.dumps(sys.argv[1:])); sys.exit(17)')
    $connectionProfile = Join-Path $root 'connection-profile.ps1'
    $existingLoader = ". '" + (Join-Path $checkout 'bin/profile.ps1').Replace("'", "''") + "'"
    [IO.File]::WriteAllText($connectionProfile, $existingLoader + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($true))
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        # A fake oh-my-posh must receive the checkout theme; its output is evaluated.
        $poshBin = Join-Path $root 'fake posh bin'
        [IO.Directory]::CreateDirectory($poshBin) | Out-Null
        $poshLog = Join-Path $root 'posh-init.txt'
        [IO.File]::WriteAllLines((Join-Path $poshBin 'oh-my-posh.cmd'), @(
            '@echo off', ('echo %*> "' + $poshLog + '"'),
            'echo $global:dalftuiPoshLoaded = $true'))
        $previousPath = $env:PATH
        $env:PATH = $poshBin + [IO.Path]::PathSeparator + $env:PATH
        try { . $connectionProfile } finally { $env:PATH = $previousPath }
        $poshArguments = [IO.File]::ReadAllText($poshLog)
        Assert-True ($global:dalftuiPoshLoaded -and $poshArguments.StartsWith('init pwsh --config ') -and
                     $poshArguments.Contains('oh-my-posh.omp.json')) `
            "The profile must initialise oh-my-posh with the checkout theme: $poshArguments"
    }
    . $connectionProfile
    $argumentJson = dssh 'alice@vm-alias'
    $arguments = ConvertFrom-Json -InputObject $argumentJson
    Assert-True (($arguments -join ' ') -eq '--connect alice@vm-alias') "dssh HOST must preserve its host and route through the launcher: $argumentJson"
    Assert-True ($LASTEXITCODE -eq 17) 'dssh must preserve the launcher exit status'
    $argumentJson = dssh
    $arguments = ConvertFrom-Json -InputObject $argumentJson
    Assert-True (($arguments -join ' ') -eq '--pick') "dssh without a host must open the picker: $argumentJson"
    Assert-Throws { dssh server unexpected } 'Unsupported positional arguments must not be silently ignored'
    [IO.File]::WriteAllText((Join-Path $checkout 'bin/ssh_picker.py'), 'import json, sys; print(json.dumps(sys.argv[1:])); sys.exit(0)')
    . $connectionProfile
    $null = dssh
    Assert-True ($LASTEXITCODE -eq 0) 'Repeated profile loading must not capture or reuse an old exit status'
    [IO.File]::WriteAllText((Join-Path $checkout 'bin/ssh_picker.py'), 'import json, sys; print(json.dumps(sys.argv[1:])); sys.exit(17)')
    # Run the local editor callback with a fake Python backend. The folder is
    # passed as one argument, including drive letters and shell metacharacters.
    [IO.File]::WriteAllText((Join-Path $checkout 'bin/vscode.py'), 'import json, sys; print(json.dumps(sys.argv[1:]))')
    $editorFolder = Join-Path $root ("project's %cash & " + [char]0xe9)
    [IO.Directory]::CreateDirectory($editorFolder) | Out-Null
    Push-Location -LiteralPath $editorFolder
    try {
        $argumentJson = Open-DalftuiCurrentFolder
        $arguments = ConvertFrom-Json -InputObject $argumentJson
        Assert-True ($arguments.Count -eq 2 -and $arguments[0] -eq '--folder' -and $arguments[1] -eq $editorFolder) 'Editor callback must use the current folder and preserve its path'
    } finally { Pop-Location }
    # Windows PowerShell ships an older PSReadLine without the -Chord option on Get-PSReadLineKeyHandler.
    $handlers = @(Get-PSReadLineKeyHandler)
    $handler = $handlers | Where-Object { $_.Key -eq 'Ctrl+b,F3' }
    Assert-True ($handler.Function -eq 'DalftuiOpenFolderInCode') 'Translated Terminal shortcut must have a local PowerShell handler'
    Assert-True ((Get-PSReadLineOption).EditMode -eq 'Emacs') 'The profile must enable Emacs editing'
    foreach ($binding in @(@('Ctrl+b,Ctrl+b', 'BackwardChar'), @('Ctrl+LeftArrow', 'BackwardWord'), @('Ctrl+RightArrow', 'ForwardWord'))) {
        $handler = $handlers | Where-Object { $_.Key -eq $binding[0] }
        Assert-True ($handler.Function -eq $binding[1]) "$($binding[0]) must run $($binding[1])"
    }
    $handler = $handlers | Where-Object { $_.Key -in @('Shift+Ctrl+F3', 'Ctrl+Shift+F3') }
    Assert-True ($handler.Function -eq 'DalftuiOpenFolderInCode') 'Native Ctrl+Shift+F3 must also work at a PowerShell prompt'
    # Exercise the bin Terminal launcher in a fresh process without a personal
    # PowerShell profile before generating settings.
    $shellName = 'powershell.exe'
    if ($PSVersionTable.PSVersion.Major -ge 6) { $shellName = 'pwsh.exe' }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { $shellName = 'pwsh' }
    $terminalShell = Join-Path $PSHOME $shellName
    $argumentJson = & $terminalShell -NoLogo -NoProfile -File (Join-Path $checkout 'bin/ssh-tab.ps1')
    $arguments = ConvertFrom-Json -InputObject $argumentJson
    Assert-True (($arguments -join ' ') -eq '--pick') 'The Terminal launcher must forward --pick without a personal profile'
    Assert-True ($LASTEXITCODE -eq 17) 'The Terminal launcher must preserve SSH/picker exit status'

    # Unix-like aliases need their tools. Load the profile at global scope in a
    # fresh shell, first without the tools, then with fakes that echo arguments.
    $fakeTools = Join-Path $root 'fake unix tools'
    $noTools = Join-Path $root 'no unix tools'
    [IO.Directory]::CreateDirectory($fakeTools) | Out-Null
    [IO.Directory]::CreateDirectory($noTools) | Out-Null
    foreach ($tool in @('lsd', 'wget2', 'btop', 'gsudo', 'bat', 'du')) {
        if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
            [IO.File]::WriteAllText((Join-Path $fakeTools "$tool.cmd"), "@echo $tool %*")
        } else {
            [IO.File]::WriteAllText((Join-Path $fakeTools $tool), "#!/bin/sh`necho $tool `"`$@`"`n")
            chmod +x (Join-Path $fakeTools $tool)
        }
    }
    $unixScript = Join-Path $root 'unix-aliases.ps1'
    [IO.File]::WriteAllLines($unixScript, @(
        '$ErrorActionPreference = ''Stop''',
        'if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {',
        '    # Like Windows PowerShell 5.1, whose ls and cat are AllScope aliases.',
        '    Set-Alias ls Get-ChildItem -Option AllScope -Scope Global',
        '    Set-Alias cat Get-Content -Option AllScope -Scope Global',
        '}',
        'function Get-UnixNames {',
        '    (@(''ls'', ''cat'', ''wget'', ''htop'', ''sudo'', ''du'') | ForEach-Object {',
        '        $command = Get-Command $_ -ErrorAction SilentlyContinue | Select-Object -First 1',
        '        "$_=$($command.CommandType):$(if ($command.CommandType -eq ''Alias'') { $command.Definition })"',
        '    }) -join '' ''',
        '}',
        '$env:PATH = $env:DALFTUI_TEST_NO_TOOLS',
        ('. ' + (ConvertTo-DalftuiSingleQuotedLiteral $connectionProfile)),
        'Get-UnixNames',
        '$env:PATH = $env:DALFTUI_TEST_FAKE_TOOLS',
        ('. ' + (ConvertTo-DalftuiSingleQuotedLiteral $connectionProfile)),
        'Get-UnixNames',
        'cat ''some file.txt'''), [Text.UTF8Encoding]::new($true))
    $env:DALFTUI_TEST_NO_TOOLS = $noTools
    $env:DALFTUI_TEST_FAKE_TOOLS = $fakeTools
    try {
        $unixOutput = @(& $terminalShell -NoLogo -NoProfile -Command (
            '. ' + (ConvertTo-DalftuiSingleQuotedLiteral $unixScript)))
    } finally {
        Remove-Item Env:DALFTUI_TEST_NO_TOOLS, Env:DALFTUI_TEST_FAKE_TOOLS
    }
    Assert-True ($LASTEXITCODE -eq 0 -and $unixOutput.Count -eq 3) "The profile must load with and without Unix tools: $unixOutput"
    Assert-True ($unixOutput[0] -match '^ls=Alias:Get-ChildItem cat=Alias:Get-Content ' -and
                 $unixOutput[0] -notmatch 'wget2|btop|gsudo' -and $unixOutput[0] -match ' du=Function:$') `
        "Missing Unix tools must keep the built-in commands: $($unixOutput[0])"
    Assert-True ($unixOutput[1] -eq 'ls=Alias:lsd cat=Function: wget=Alias:wget2 htop=Alias:btop sudo=Alias:gsudo du=Application:') `
        "Installed Unix tools must replace the built-in commands: $($unixOutput[1])"
    # A Windows .cmd fake echoes the quotes PowerShell adds around "some file.txt".
    Assert-True (($unixOutput[2] -replace '"') -eq 'bat --style=plain some file.txt') "cat must run bat: $($unixOutput[2])"

    Push-Location -LiteralPath $root
    try {
        touch 'touch a.txt' 'touch b.txt'
        Assert-True ((Test-Path 'touch a.txt') -and (Test-Path 'touch b.txt')) 'touch must create every file'
        (Get-Item 'touch a.txt').LastWriteTime = [datetime]'2020-01-01'
        touch 'touch a.txt'
        Assert-True ((Get-Item 'touch a.txt').LastWriteTime.Year -gt 2020) 'touch must update an existing file'
        # A real wc on PATH (Linux, Git for Windows) replaces the profile's function.
        if ((Get-Command wc | Select-Object -First 1).CommandType -eq 'Function') {
            Assert-True ((@('one two', 'three') | wc -l -w) -eq "2`t3") 'wc -l -w must count piped text'
        }
    } finally { Pop-Location }

    $settingsPath = Join-Path $root 'terminal-settings.json'
    [IO.File]::WriteAllText($settingsPath, '{"actions":[],"keybindings":[]}')
    $python = Find-DalftuiApplication 'py'
    $pythonArguments = @('-3')
    if (-not $python) {
        $python = Find-DalftuiApplication 'python'
        $pythonArguments = @()
    }
    Set-DalftuiTerminalShortcut -Python $python.Source -PythonArguments $pythonArguments `
        -Checkout $checkout -SettingsPaths @($settingsPath)
    $settings = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($settingsPath))
    Assert-True ($settings.keybindings[0].keys -eq 'ctrl+shift+f2') 'Setup must install Ctrl+Shift+F2'
    Assert-True ($settings.actions[0].command.action -eq 'newTab') 'Shortcut must open a new tab'
    Assert-True ($settings.keybindings[1].keys -eq 'ctrl+shift+f3') 'Setup must install Ctrl+Shift+F3'
    Assert-True ($settings.actions[1].command.input -eq ([char]2 + [string][char]27 + 'OR')) 'Editor shortcut must send the existing tmux F3 sequence'
    Assert-True ($settings.actions[0].command.commandline.Contains(
                    (Join-Path $checkout 'bin/ssh-tab.ps1'))) `
        'Generated Terminal actions must target the bin launcher'
    $installedSettings = [IO.File]::ReadAllBytes($settingsPath)
    $terminalBackups = @(Get-ChildItem -LiteralPath $root -Filter 'terminal-settings.json*.bak')
    Set-DalftuiTerminalShortcut -Python $python.Source -PythonArguments $pythonArguments `
        -Checkout $checkout -SettingsPaths @($settingsPath)
    Assert-True ([Convert]::ToBase64String($installedSettings) -eq
                 [Convert]::ToBase64String([IO.File]::ReadAllBytes($settingsPath))) `
        'An unchanged setup must not rewrite an already configured Terminal action'
    Assert-True (@(Get-ChildItem -LiteralPath $root -Filter 'terminal-settings.json*.bak').Count -eq
                 $terminalBackups.Count) `
        'An idempotent Terminal rerun must not create another backup'
    Assert-True (-not $settings.profiles.PSObject.Properties['list']) `
        'Without PowerShell 7, setup must not add Terminal profiles'
    $vscodeSettingsPath = Join-Path $root 'vscode-settings.json'
    [IO.File]::WriteAllText($vscodeSettingsPath, "{`r`n    // personal`r`n}`r`n")
    Set-DalftuiTerminalShortcut -Python $python.Source -PythonArguments $pythonArguments `
        -Checkout $checkout -SettingsPaths @($settingsPath) -VSCodeSettingsPath $vscodeSettingsPath
    $vscodeText = [IO.File]::ReadAllText($vscodeSettingsPath)
    Assert-True ($vscodeText.Contains('// personal') -and
                 $vscodeText.Contains('"terminal.integrated.fontFamily": "Hack Nerd Font"') -and
                 $vscodeText.Contains('"terminal.integrated.fontSize": 12')) `
        "Setup must set the VS Code terminal font and keep comments: $vscodeText"
    $fakePwsh = Join-Path $root 'Power Shell\pwsh.exe'
    foreach ($run in 1, 2) {
        Set-DalftuiTerminalShortcut -Python $python.Source -PythonArguments $pythonArguments `
            -Checkout $checkout -SettingsPaths @($settingsPath) -PowerShell7 $fakePwsh
        if ($run -eq 1) { $installedSettings = [IO.File]::ReadAllBytes($settingsPath) }
    }
    Assert-True ([Convert]::ToBase64String($installedSettings) -eq
                 [Convert]::ToBase64String([IO.File]::ReadAllBytes($settingsPath))) `
        'A PowerShell 7 profile rerun must not rewrite Terminal settings'
    $profiles = @((ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($settingsPath))).profiles.list)
    Assert-True ($profiles.Count -eq 2 -and $profiles[0].source -eq 'Windows.Terminal.PowershellCore' -and
                 $profiles[1].name -eq 'Windows PowerShell 7 (Admin)' -and $profiles[1].elevate -and
                 $profiles[1].commandline -eq ('"' + $fakePwsh + '"')) `
        "Setup must customize PowerShell 7 and add an elevated copy: $($profiles | ConvertTo-Json -Compress)"
    # Uninstall removes only setup's block, keeps the rest and reports a second run.
    $uninstallProfile = Join-Path $root 'uninstall profile.ps1'
    $personalText = "# personal " + [char]0xe9 + "`r`nfunction dssh { 'old' }`r`n"
    [IO.File]::WriteAllText($uninstallProfile, $personalText, [Text.Encoding]::Unicode)
    Write-DalftuiProfile -Path $uninstallProfile -Checkout $checkout
    $installedBytes = [IO.File]::ReadAllBytes($uninstallProfile)
    Remove-DalftuiProfile -Path $uninstallProfile -DryRun
    Assert-True ([Convert]::ToBase64String($installedBytes) -eq
                 [Convert]::ToBase64String([IO.File]::ReadAllBytes($uninstallProfile))) 'A dry run must leave the profile unchanged'
    $backupCount = @(Get-ChildItem -LiteralPath $root -Filter 'uninstall profile.ps1*.bak').Count
    Remove-DalftuiProfile -Path $uninstallProfile
    Assert-True ([IO.File]::ReadAllText($uninstallProfile) -eq $personalText) 'Uninstall must keep personal profile text and line endings'
    Assert-True (@(Get-ChildItem -LiteralPath $root -Filter 'uninstall profile.ps1*.bak').Count -eq $backupCount + 1) `
        'Uninstall must back up the profile it changes'
    $uninstalledBytes = [IO.File]::ReadAllBytes($uninstallProfile)
    Assert-True ($uninstalledBytes[0] -eq 0xEF -and $uninstalledBytes[1] -eq 0xBB) 'Uninstall must keep the profile encoding'
    $output = Remove-DalftuiProfile -Path $uninstallProfile 6>&1 | Out-String
    Assert-True ($output.Contains('No dalftui block') -and
                 @(Get-ChildItem -LiteralPath $root -Filter 'uninstall profile.ps1*.bak').Count -eq $backupCount + 1) `
        'A second uninstall must report nothing to remove'
    $editedBlock = "# >>> dalftui >>>`n. 'C:\old\bin/profile.ps1'`nSet-Alias x y`n# <<< dalftui <<<`n"
    [IO.File]::WriteAllText($uninstallProfile, $editedBlock)
    Remove-DalftuiProfile -Path $uninstallProfile -WarningAction SilentlyContinue
    Assert-True ([IO.File]::ReadAllText($uninstallProfile) -eq $editedBlock) 'A block with personal lines must be kept'

    # Exercise -Uninstall end to end on the settings installed above.
    Write-DalftuiProfile -Path $uninstallProfile -Checkout $checkout
    [IO.File]::WriteAllText($uninstallProfile, "# mine`n" + [IO.File]::ReadAllText($uninstallProfile))
    $before = @($uninstallProfile, $settingsPath, $vscodeSettingsPath) | ForEach-Object { [Convert]::ToBase64String([IO.File]::ReadAllBytes($_)) }
    & {
        function Test-DalftuiWindowsPlatform { return $true }
        function Get-DalftuiInstalledVSCodeSettingsPath([string]$RequestedPath) { return $vscodeSettingsPath }
        Invoke-DalftuiWindowsSetup -Uninstall -DryRun -TargetProfile $uninstallProfile -Checkout $checkout `
            -SettingsPaths @($settingsPath) | Out-Null
        $after = @($uninstallProfile, $settingsPath, $vscodeSettingsPath) | ForEach-Object { [Convert]::ToBase64String([IO.File]::ReadAllBytes($_)) }
        Assert-True (($before -join ',') -eq ($after -join ',')) 'An uninstall dry run must change no file'
        Invoke-DalftuiWindowsSetup -Uninstall -TargetProfile $uninstallProfile -Checkout $checkout `
            -SettingsPaths @($settingsPath) | Out-Null
    }
    Assert-True ([IO.File]::ReadAllText($uninstallProfile) -eq "# mine`n") 'Uninstall must remove the profile block'
    $terminalText = [IO.File]::ReadAllText($settingsPath)
    Assert-True (-not $terminalText.Contains('Dalftui') -and -not $terminalText.Contains('Hack Nerd Font') -and
                 -not $terminalText.Contains('Windows PowerShell 7 (Admin)')) "Uninstall must remove Terminal entries: $terminalText"
    $vscodeText = [IO.File]::ReadAllText($vscodeSettingsPath)
    Assert-True ($vscodeText.Contains('// personal') -and -not $vscodeText.Contains('terminal.integrated')) `
        "Uninstall must remove the VS Code font and keep comments: $vscodeText"
    # A -VSCodePath whose Code.exe was removed still finds portable data, or is skipped.
    $removedCode = Join-Path $root 'removed VS Code'
    [IO.Directory]::CreateDirectory((Join-Path $removedCode 'data')) | Out-Null
    Assert-True ((Get-DalftuiInstalledVSCodeSettingsPath $removedCode) -eq
                 (Join-Path $removedCode 'data\user-data\User\settings.json')) 'Uninstall must find portable data without Code.exe'
    Assert-True ($null -eq (Get-DalftuiInstalledVSCodeSettingsPath (Join-Path $root 'missing') 3>$null)) `
        'A missing -VSCodePath must skip VS Code instead of failing'
    & {
        function Test-DalftuiWindowsPlatform { return $true }
        Assert-Throws { Invoke-DalftuiWindowsSetup -DryRun -TargetProfile $uninstallProfile -NoTerminal } `
            '-DryRun without -Uninstall must be rejected'
    }
    Write-Host "Passed $checks Windows setup assertions."
    # The exit-status test above deliberately ran a failing native command.
    $global:LASTEXITCODE = 0
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force
}
