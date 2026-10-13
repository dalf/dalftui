#requires -Version 5.1
param(
    [string]$Checkout = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
)

# Terminal's Ctrl+Shift+F2 action runs this file in a new tab without depending
# on a personal profile. The tab never shows a prompt, so it skips the
# interactive profile and finds Python with uv.exe, never a batch shim.
$ErrorActionPreference = 'Stop'
try {
    if (Get-Command mise -CommandType Application -ErrorAction SilentlyContinue) {
        # The profile activates mise; its environment is enough here and much cheaper.
        # It can supply uv.exe, Python and [env] variables such as SSH_AUTH_SOCK.
        # mise prints nothing when it cannot start, such as without the VC++ runtime.
        $ErrorActionPreference = 'Continue'
        $dalftuiMise = & mise env -s pwsh 2>$null | Out-String
        $ErrorActionPreference = 'Stop'
        if ($dalftuiMise.Trim()) { Invoke-Expression $dalftuiMise }
    }
    $picker = Join-Path $Checkout 'bin/ssh_picker.py'
    # The picker needs only a Python 3.11+, and asking uv for one costs about
    # 350 ms per tab, so remember the interpreter uv found and run it directly.
    # Like setup, accept only a fully qualified LOCALAPPDATA.
    $cache = $null
    if ($env:LOCALAPPDATA -match '\A(?:[A-Za-z]:[\\/]|[\\/]{2})') {
        $cache = Join-Path $env:LOCALAPPDATA 'dalftui\python-path.txt'
    }
    $isPython = { param($Path) $Path -match '\A(?:[A-Za-z]:[\\/]|[\\/]{2}).*[\\/]python[0-9.]*\.exe\z' -and [IO.File]::Exists($Path) }
    # Exit with the picker's status, or return when this Python cannot start: it is
    # not a program, or a DLL it needs is gone (STATUS_DLL_NOT_FOUND).
    $runPicker = {
        param($Python)
        try { & $Python $picker --pick }
        catch [Management.Automation.ApplicationFailedException], [Management.Automation.CommandNotFoundException] { return }
        if ($LASTEXITCODE -ne -1073741515) { exit $LASTEXITCODE }
    }
    if ($cache -and [IO.File]::Exists($cache)) {
        $python = $null
        try { $python = [IO.File]::ReadAllText($cache).Trim() } catch { }
        if (& $isPython $python) { & $runPicker $python }
    }
    . (Join-Path $PSScriptRoot 'find-uv.ps1')
    $uv = & $dalftuiFindUv
    if (-not $uv) {
        throw 'uv is required. Install it (scoop install uv), then open a new tab.'
    }
    if ($cache) {
        $temporary = "$cache.$PID.tmp"
        $python = $null
        try {
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($cache)) | Out-Null
            # Like bootstrap.cmd, uv run downloads a Python when none is found. It
            # also picks a .venv in or above the tab's starting directory, or
            # VIRTUAL_ENV; remember the base interpreter, which outlives that venv.
            # Python writes UTF-8 itself, so non-ASCII paths survive the console.
            & $uv.Source run --no-project --python '>=3.11' python -c "import sys; open(sys.argv[1], 'w', encoding='utf-8').write(getattr(sys, '_base_executable', sys.executable))" $temporary
            if ($LASTEXITCODE -eq 0 -and (& $isPython ($found = [IO.File]::ReadAllText($temporary)))) {
                $python = $found
                if ([IO.File]::Exists($cache)) { [IO.File]::Replace($temporary, $cache, [NullString]::Value) }
                else { [IO.File]::Move($temporary, $cache) }
            }
        } catch { }
        finally { if ([IO.File]::Exists($temporary)) { Remove-Item -LiteralPath $temporary -ErrorAction SilentlyContinue } }
        if ($python) { & $runPicker $python }
    }
    # Without a usable cache, run the picker through uv as before.
    & $uv.Source run --no-project --python '>=3.11' $picker --pick
    exit $LASTEXITCODE
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}