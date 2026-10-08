@rem A parenthesized block: cmd reads it whole before bootstrap's git pull can rewrite this file.
@rem uv only finds (or downloads) Python and exits, so bootstrap can update uv with Scoop.
@setlocal
@(
  where /q scoop && where /q git && where /q uv || goto missing
  set "DALFTUI_BOOTSTRAP_PYTHON="
  for /f "delims=" %%p in ('uv run --no-project --python ">=3.11" python -c "import sys; print(sys.executable)"') do @set "DALFTUI_BOOTSTRAP_PYTHON=%%p"
  if not defined DALFTUI_BOOTSTRAP_PYTHON goto nopython
  call "%%DALFTUI_BOOTSTRAP_PYTHON%%" "%~dp0bootstrap" %*
  call exit /b %%ERRORLEVEL%%
)
:missing
@>&2 echo Bootstrap failed: Scoop, Git and uv are required. In a non-elevated PowerShell: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned; irm get.scoop.sh ^| iex; scoop install git uv
@exit /b 1
:nopython
@>&2 echo Bootstrap failed: uv found no Python 3.11 or newer; see its error above.
@exit /b 1
