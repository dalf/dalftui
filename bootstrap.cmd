@rem A parenthesized block: cmd reads it whole before bootstrap's git pull can rewrite this file.
@(
  where /q scoop && where /q git && where /q uv || goto missing
  uv run --no-project --python ">=3.11" --script "%~dp0bootstrap" %*
  call exit /b %%ERRORLEVEL%%
)
:missing
@1>&2 echo Bootstrap failed: Scoop, Git and uv are required. In a non-elevated PowerShell: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned; irm get.scoop.sh ^| iex; scoop install git uv
@exit /b 1
