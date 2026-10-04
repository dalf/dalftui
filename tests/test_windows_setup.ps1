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
    foreach ($file in @('setup-windows.ps1', 'windows.ps1')) {
        $parseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo $file),
            [ref]$null, [ref]$parseErrors) | Out-Null
        Assert-True (-not $parseErrors) "$file must parse in this PowerShell version"
    }

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
    Write-Host "Passed $checks Windows setup assertions."
    # The exit-status test above deliberately ran a failing native command.
    $global:LASTEXITCODE = 0
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force
}
