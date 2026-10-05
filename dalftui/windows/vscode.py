"""Read the VS Code application selected by Windows setup."""
import json
from pathlib import Path
import re

WINDOWS_CONFIG = Path('dalftui') / 'config.json'


def windows_cli_path(application):
    """Read the active CLI from code.cmd, without executing the batch launcher."""
    launcher = application.parent / 'bin/code.cmd'
    try:
        contents = launcher.read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        contents = ''
    # Updates can leave several version directories, including an old flat
    # resources tree. Follow only the installed launcher's relative CLI path.
    match = re.search(
        r'^\s*"%~dp0\.\.[\\/]Code\.exe"\s+"%~dp0\.\.[\\/]'
        r'(?P<cli>(?:[0-9a-f]+[\\/])?resources[\\/]app[\\/]out[\\/]cli\.js)"',
        contents, re.IGNORECASE | re.MULTILINE)
    if match:
        return application.parent.joinpath(*re.split(r'[\\/]', match['cli']))
    return application.parent / 'resources/app/out/cli.js'


def windows_code_command(env):
    """Load the absolute VS Code application selected by Windows setup."""
    recovery = ("Rerun dalftui's install.cmd. For a portable installation, "
                "pass -VSCodePath with its directory or Code.exe path.")
    local_app_data = env.get('LOCALAPPDATA')
    if not local_app_data or not Path(local_app_data).is_absolute():
        raise RuntimeError(f'VS Code is not configured. {recovery}')
    config_path = Path(local_app_data) / WINDOWS_CONFIG
    try:
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        raise RuntimeError(f'VS Code is not configured. {recovery}') from None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f'Cannot read the VS Code configuration at {config_path}. '
                           f'{recovery}') from error
    application_value = config.get('code') if isinstance(config, dict) else None
    if not isinstance(application_value, str) or '\0' in application_value:
        raise RuntimeError(f'The VS Code configuration at {config_path} is invalid. {recovery}')
    application = Path(application_value)
    if not application.is_absolute() or application.name.lower() != 'code.exe':
        raise RuntimeError(f'The VS Code configuration at {config_path} is invalid. {recovery}')
    try:
        cli = windows_cli_path(application)
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f'Cannot read the configured VS Code launcher at {application}. '
                           f'{recovery}') from error
    if not application.is_file() or not cli.is_file():
        raise RuntimeError(f'The configured VS Code installation is missing: {application}. '
                           f'{recovery}')
    env['ELECTRON_RUN_AS_NODE'] = '1'
    env.pop('VSCODE_DEV', None)
    return [str(application), str(cli)]
