@echo off
setlocal
rem Rebuild Windows PowerShell module paths when called through cmd from pwsh.
set "PSModulePath="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %ERRORLEVEL%
