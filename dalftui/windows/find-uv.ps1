#requires -Version 5.1
# Dot-sourced by profile.ps1 and ssh-tab.ps1: one uv lookup for both.
# A batch shim such as mise's uv.cmd passes arguments through cmd.exe, which
# reads >=3.11 as a redirection; only uv.exe receives them intact.
$dalftuiFindUv = {
    Get-Command uv -CommandType Application -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -eq '.exe' } | Select-Object -First 1
}
