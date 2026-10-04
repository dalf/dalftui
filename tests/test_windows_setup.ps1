#requires -Version 5.1
# Standalone assertions: no Pester, package installations, or personal profiles.
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
. (Join-Path $repo 'setup-windows.ps1')
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
try {
    foreach ($file in @('setup-windows.ps1', 'windows.ps1', 'windows-terminal.ps1')) {
        $parseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo $file),
            [ref]$null, [ref]$parseErrors) | Out-Null
        Assert-True (-not $parseErrors) "$file must parse in this PowerShell version"
    }

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

    $originalFind = (Get-Item Function:\Find-DalftuiApplication).ScriptBlock
    $originalInstall = (Get-Item Function:\Invoke-DalftuiPackageInstall).ScriptBlock
    $originalPath = (Get-Item Function:\Update-DalftuiProcessPath).ScriptBlock
    $script:apps = @{}
    function Find-DalftuiApplication([string]$Name) { $script:apps[$Name] }
    $winget = [pscustomobject]@{ Name = 'winget.exe'; Source = 'winget.exe' }
    $choco = [pscustomobject]@{ Name = 'choco.exe'; Source = 'choco.exe' }
    $script:apps = @{winget = $winget; choco = $choco}
    Assert-True ((Select-DalftuiPackageManager).Name -eq 'winget.exe') 'Auto must prefer WinGet'
    Assert-True ((Select-DalftuiPackageManager choco).Name -eq 'choco.exe') 'Explicit Chocolatey must be respected'
    $script:apps.Remove('winget')
    Assert-True ((Select-DalftuiPackageManager).Name -eq 'choco.exe') 'Auto must use Chocolatey without WinGet'
    $script:apps = @{}
    Assert-True ($null -eq (Select-DalftuiPackageManager)) 'No package manager must return no selection'
    Assert-Throws { Select-DalftuiPackageManager winget } 'An unavailable explicit manager must fail'

    $script:installs = 0
    $script:pathUpdates = 0
    function Invoke-DalftuiPackageInstall($Manager) {
        $script:installs++
        $script:apps.fzf = [pscustomobject]@{Name = 'fzf.exe'; Source = 'fzf.exe'}
    }
    function Update-DalftuiProcessPath { $script:pathUpdates++ }
    $script:apps = @{fzf = [pscustomobject]@{Name = 'fzf.exe'; Source = 'fzf.exe'}}
    Assert-True (Install-DalftuiFzf -Preference choco) 'Existing fzf must be reused even without its installer'
    Assert-True ($script:installs -eq 0) 'Existing fzf must never be reinstalled'
    $script:apps = @{}
    Assert-True (-not (Install-DalftuiFzf -Skip)) 'SkipFzf must avoid installation'
    Assert-True (-not (Install-DalftuiFzf -WarningAction SilentlyContinue)) 'No package manager must allow direct-connection setup'
    Assert-True ($script:installs -eq 0) 'Missing/skipped managers must never run an installer'
    $script:apps = @{winget = $winget}
    Assert-True (Install-DalftuiFzf) 'A successful install must enable the picker'
    Assert-True ($script:installs -eq 1 -and $script:pathUpdates -eq 1) 'Install must refresh PATH once'
    function Invoke-DalftuiPackageInstall($Manager) { throw 'test installer failure' }
    $script:apps = @{winget = $winget; choco = $choco}
    Assert-Throws { Install-DalftuiFzf } 'Installation failure must propagate instead of switching package managers'
    Set-Item Function:\Invoke-DalftuiPackageInstall $originalInstall

    # Capture the exact manager arguments without running either package manager.
    $capture = Join-Path $root 'manager-arguments.txt'
    $fakeManager = Join-Path $root 'fake-manager.ps1'
    $escapedCapture = $capture.Replace("'", "''")
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        # PowerShell 5.1 parses script parameters differently from native argv.
        $fakeManager = Join-Path $root 'fake-manager.cmd'
        [IO.File]::WriteAllText($fakeManager, "@echo off`r`necho %* > `"$capture`"`r`nexit /b 0`r`n")
    } else {
        [IO.File]::WriteAllText($fakeManager, "(`$args -join ' ') | Set-Content -LiteralPath '$escapedCapture'; `$global:LASTEXITCODE = 0")
    }
    Invoke-DalftuiPackageInstall ([pscustomobject]@{Name = 'winget.exe'; Source = $fakeManager})
    $arguments = [IO.File]::ReadAllText($capture).Trim()
    Assert-True ($arguments -eq 'install --id junegunn.fzf --exact --source winget --accept-package-agreements --accept-source-agreements') "WinGet arguments must install the exact fzf package: $arguments"
    Invoke-DalftuiPackageInstall ([pscustomobject]@{Name = 'choco.exe'; Source = $fakeManager})
    $arguments = [IO.File]::ReadAllText($capture).Trim()
    Assert-True ($arguments -eq 'install fzf --yes --no-progress') "Chocolatey arguments must install only fzf: $arguments"
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        [IO.File]::WriteAllText($fakeManager, "@echo off`r`nexit /b 17`r`n")
    } else {
        [IO.File]::WriteAllText($fakeManager, '$global:LASTEXITCODE = 17')
    }
    Assert-Throws { Invoke-DalftuiPackageInstall ([pscustomobject]@{Name = 'winget.exe'; Source = $fakeManager}) } 'A nonzero manager status must fail setup'
    Set-Item Function:\Find-DalftuiApplication $originalFind
    Set-Item Function:\Update-DalftuiProcessPath $originalPath

    $checkout = Join-Path $root ("repo's unicode " + [char]0xe9)
    [IO.Directory]::CreateDirectory($checkout) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo 'windows.ps1') -Destination $checkout
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
    [IO.Directory]::CreateDirectory($moved) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo 'windows.ps1') -Destination $moved
    Write-DalftuiProfile -Path $profile -Checkout $moved
    Assert-True ([IO.File]::ReadAllText($profile).Contains($moved)) 'Rerunning from a moved checkout must update the loader'
    Assert-True ([IO.File]::ReadAllText($profile).StartsWith($existing)) 'Moving a checkout must preserve personal settings'
    [IO.File]::WriteAllText($profile, '# >>> dalftui >>>')
    Assert-Throws { Write-DalftuiProfile -Path $profile -Checkout $checkout } 'An incomplete block must not be overwritten'
    Assert-True ([IO.File]::ReadAllText($profile) -eq '# >>> dalftui >>>') 'Malformed profile must remain untouched'

    # Exercise the real profile -> closure -> Python path without SSH or a GUI.
    [IO.File]::WriteAllText((Join-Path $checkout 'ssh-picker.py'), 'import json, sys; print(json.dumps(sys.argv[1:])); sys.exit(17)')
    Write-DalftuiProfile -Path (Join-Path $root 'connection-profile.ps1') -Checkout $checkout
    . (Join-Path $root 'connection-profile.ps1')
    $argumentJson = dssh 'alice@vm-alias'
    $arguments = ConvertFrom-Json -InputObject $argumentJson
    Assert-True (($arguments -join ' ') -eq '--connect alice@vm-alias') "dssh HOST must preserve its host and route through the launcher: $argumentJson"
    Assert-True ($LASTEXITCODE -eq 17) 'dssh must preserve the launcher exit status'
    $argumentJson = dssh
    $arguments = ConvertFrom-Json -InputObject $argumentJson
    Assert-True (($arguments -join ' ') -eq '--pick') "dssh without a host must open the picker: $argumentJson"
    Assert-Throws { dssh server unexpected } 'Unsupported positional arguments must not be silently ignored'
    [IO.File]::WriteAllText((Join-Path $checkout 'ssh-picker.py'), 'import json, sys; print(json.dumps(sys.argv[1:])); sys.exit(0)')
    $null = dssh
    Assert-True ($LASTEXITCODE -eq 0) 'Successful dssh must not reuse an exit status captured when the profile loaded'
    [IO.File]::WriteAllText((Join-Path $checkout 'ssh-picker.py'), 'import json, sys; print(json.dumps(sys.argv[1:])); sys.exit(17)')
    # Run the local editor callback with a fake Python backend. The folder is
    # passed as one argument, including drive letters and shell metacharacters.
    [IO.File]::WriteAllText((Join-Path $checkout 'vscode.py'), 'import json, sys; print(json.dumps(sys.argv[1:]))')
    $editorFolder = Join-Path $root ("project's %cash & " + [char]0xe9)
    [IO.Directory]::CreateDirectory($editorFolder) | Out-Null
    Push-Location -LiteralPath $editorFolder
    try {
        $argumentJson = Open-DalftuiCurrentFolder
        $arguments = ConvertFrom-Json -InputObject $argumentJson
        Assert-True ($arguments.Count -eq 2 -and $arguments[0] -eq '--folder' -and $arguments[1] -eq $editorFolder) 'Editor callback must use the current folder and preserve its path'
    } finally { Pop-Location }
    # Windows PowerShell ships an older PSReadLine without Get's -Chord option.
    $handlers = @(Get-PSReadLineKeyHandler)
    $handler = $handlers | Where-Object { $_.Key -eq 'Ctrl+b,F3' }
    Assert-True ($handler.Function -eq 'DalftuiOpenFolderInCode') 'Translated Terminal shortcut must have a local PowerShell handler'
    $handler = $handlers | Where-Object { $_.Key -in @('Shift+Ctrl+F3', 'Ctrl+Shift+F3') }
    Assert-True ($handler.Function -eq 'DalftuiOpenFolderInCode') 'Native Ctrl+Shift+F3 must also work at a PowerShell prompt'
    # Exercise the real new-tab launcher without a GUI or SSH connection.
    foreach ($file in @('windows-terminal.py', 'windows-terminal.ps1')) {
        Copy-Item -LiteralPath (Join-Path $repo $file) -Destination $checkout
    }
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
    $shellName = 'powershell.exe'
    if ($PSVersionTable.PSVersion.Major -ge 6) { $shellName = 'pwsh.exe' }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { $shellName = 'pwsh' }
    $terminalShell = Join-Path $PSHOME $shellName
    $argumentJson = & $terminalShell -NoLogo -NoProfile -File (Join-Path $checkout 'windows-terminal.ps1')
    $arguments = ConvertFrom-Json -InputObject $argumentJson
    Assert-True (($arguments -join ' ') -eq '--pick') 'A fresh tab must run dssh without a personal PowerShell profile'
    Assert-True ($LASTEXITCODE -eq 17) 'New-tab launcher must preserve SSH/picker exit status'
    Write-Host "Passed $checks Windows setup assertions."
    # The exit-status test above deliberately ran a failing native command.
    $global:LASTEXITCODE = 0
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force
}
