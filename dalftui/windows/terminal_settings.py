"""Install the SSH picker and VS Code shortcuts, preserving Terminal settings."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
ACTION_ID = 'User.DalftuiSshPicker'
SHORTCUT = 'ctrl+shift+f2'
EDITOR_ACTION_ID = 'User.DalftuiOpenFolderInCode'
EDITOR_SHORTCUT = 'ctrl+shift+f3'
EDITOR_INPUT = '\x02\x1bOR'
PROMPT_FONT = 'Hack Nerd Font'
# Also applied by the Linux desktop installer.
VSCODE_SETTINGS = {'terminal.integrated.fontFamily': PROMPT_FONT, 'terminal.integrated.fontSize': 12}
# Windows Terminal's own PowerShell 7 profile, and a dalftui-owned elevated copy.
PWSH_GUID = '{574e775e-4f2a-5b96-ac1e-a2962a402336}'
ADMIN_GUID = '{267e52e6-0ec9-495c-a8b0-e4437770bc55}'
ADMIN_NAME = 'Windows PowerShell 7 (Admin)'
DECODER = json.JSONDecoder()
JSONC_PARTS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
TRAILING_COMMAS = re.compile(r'("(?:\\.|[^"\\])*")|,(?=\s*[}\]])')


def clean_jsonc(text):
    # Keep character offsets so edits preserve comments and unrelated formatting.
    def comments(match):
        part = match.group()
        return part if part.startswith('"') else re.sub(r'[^\r\n]', ' ', part)
    text = JSONC_PARTS.sub(comments, text)
    return TRAILING_COMMAS.sub(lambda m: m.group(1) or ' ', text)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON property: {key}')
        result[key] = value
    return result


def skip_space(text, index):
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def members(text, start, object_mode=False):
    """Return value spans from an already validated object or array."""
    index = skip_space(text, start + 1)
    closing = '}' if object_mode else ']'
    result = []
    while text[index] != closing:
        name = None
        if object_mode:
            name, index = DECODER.raw_decode(text, index)
            index = skip_space(text, index) + 1  # colon
            index = skip_space(text, index)
        begin = index
        value, index = DECODER.raw_decode(text, index)
        result.append((name, value, begin, index))
        index = skip_space(text, index)
        if text[index] == ',':
            index = skip_space(text, index + 1)
    return result, index


def normalized_key(key):
    return tuple(sorted(part.strip().lower() for part in key.split('+')))


def has_shortcut(entry, shortcut=SHORTCUT):
    keys = entry.get('keys', [])
    if isinstance(keys, str):
        keys = [keys]
    return isinstance(keys, list) and any(
        isinstance(key, str) and normalized_key(key) == normalized_key(shortcut)
        for key in keys)


def updated_settings(text, commandline, pwsh=None):
    text = shortcut_settings(text, commandline)
    return profile_settings(text, pwsh) if pwsh else text


def profile_settings(text, pwsh):
    """Use ClearType in Terminal's PowerShell 7 profile and add an elevated copy."""
    clean = clean_jsonc(text)
    profiles = json.loads(clean, object_pairs_hook=unique_object).get('profiles')
    if not isinstance(profiles, dict):
        return text  # The legacy profiles array is left unchanged.
    root_items, _ = members(clean, skip_space(clean, 0), object_mode=True)
    begin = next(begin for name, _, begin, _ in root_items if name == 'profiles')
    items, end = members(clean, begin, object_mode=True)
    cleartype = '"antialiasingMode": "cleartype"'
    stub = {'guid': PWSH_GUID, 'source': 'Windows.Terminal.PowershellCore'}
    admin = {'guid': ADMIN_GUID, 'name': ADMIN_NAME, 'commandline': pwsh, 'elevate': True,
             'startingDirectory': '%USERPROFILE%', 'icon': 'ms-appx:///ProfileIcons/pwsh.png'}
    defaults = profiles.get('defaults')
    keep_mode = isinstance(defaults, dict) and 'antialiasingMode' in defaults
    if not keep_mode:  # A mode chosen in profiles.defaults applies to every profile.
        stub['antialiasingMode'] = admin['antialiasingMode'] = 'cleartype'
    newline = '\r\n' if '\r\n' in text else '\n'
    edits = []
    found = [item for item in items if item[0] == 'list']
    if not found:
        append_entry(text, items, end, '"list": ' + json.dumps([stub, admin], ensure_ascii=False), newline, edits)
    else:
        _, entries, begin, _ = found[0]
        if not isinstance(entries, list):
            raise ValueError('Terminal profiles.list must be an array.')
        items, end = members(clean, begin)
        additions = []
        for profile in (stub, admin):
            # Match by name too: profiles from the old setup gist have random GUIDs.
            keys = {('guid', profile['guid'].lower())}
            if 'name' in profile:
                keys.add(('name', profile['name'].lower()))
            owned = [item for item in items if isinstance(item[1], dict) and any(
                (key, str(item[1].get(key)).lower()) in keys for key in ('guid', 'name'))]
            if not owned:
                additions.append(json.dumps(profile, ensure_ascii=False))
            elif profile is stub and not keep_mode and 'antialiasingMode' not in owned[0][1]:
                entry_items, entry_end = members(clean, owned[0][2], object_mode=True)
                append_entry(text, entry_items, entry_end, cleartype, newline, edits)
        if additions:
            append_entry(text, items, end, (',' + newline + '    ').join(additions), newline, edits)
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


def shortcut_settings(text, commandline):
    clean = clean_jsonc(text)
    settings = json.loads(clean, object_pairs_hook=unique_object)
    if not isinstance(settings, dict):
        raise ValueError('Terminal settings must be a JSON object.')
    root_items, root_end = members(clean, skip_space(clean, 0), object_mode=True)
    properties = {name: (value, begin, end) for name, value, begin, end in root_items}
    arrays = {}
    for name in ('actions', 'keybindings'):
        if name in properties:
            value, begin, _ = properties[name]
            if not isinstance(value, list):
                raise ValueError(f'Terminal {name} must be an array.')
            arrays[name] = members(clean, begin)
            for entry in value:
                for shortcut, action_id, label in (
                        (SHORTCUT, ACTION_ID, 'Ctrl+Shift+F2'),
                        (EDITOR_SHORTCUT, EDITOR_ACTION_ID, 'Ctrl+Shift+F3')):
                    if isinstance(entry, dict) and has_shortcut(entry, shortcut) and entry.get('id') != action_id:
                        raise ValueError(f'{label} already has a binding. Remove that binding in Terminal settings, then rerun setup. The existing settings were preserved.')

    modern = 'keybindings' in properties
    picker_action = {
        'id': ACTION_ID,
        'name': 'SSH host picker (dssh)',
        'command': {
            'action': 'newTab', 'commandline': commandline,
            'startingDirectory': '%USERPROFILE%', 'tabTitle': 'SSH',
            'suppressApplicationTitle': False, 'elevate': False,
        },
    }
    editor_action = {
        'id': EDITOR_ACTION_ID,
        'name': 'Open current folder in VS Code',
        'command': {'action': 'sendInput', 'input': EDITOR_INPUT},
    }
    actions = [(picker_action, SHORTCUT), (editor_action, EDITOR_SHORTCUT)]
    if not modern:
        # Inline keys are supported by older Terminal versions as well.
        for action, shortcut in actions:
            action['keys'] = shortcut
    desired = {'actions': actions}
    if modern:
        desired['keybindings'] = [({'id': action['id'], 'keys': shortcut}, shortcut)
                                  for action, shortcut in actions]
    edits = []
    missing = []
    newline = '\r\n' if '\r\n' in text else '\n'
    for name, entries in desired.items():
        additions = []
        if name not in arrays:
            missing.append(json.dumps(name) + ': ' + json.dumps([entry for entry, _ in entries], ensure_ascii=False))
            continue
        items, end = arrays[name]
        for entry, shortcut in entries:
            encoded = json.dumps(entry, ensure_ascii=False)
            owned = [item for item in items if isinstance(item[1], dict) and
                     item[1].get('id') == entry['id'] and
                     (name == 'actions' or has_shortcut(item[1], shortcut))]
            if len(owned) > 1:
                raise ValueError(f'Duplicate dalftui entries in {name}; remove the duplicates before rerunning setup.')
            if owned:
                _, previous, begin, finish = owned[0]
                if previous != entry:
                    edits.append((begin, finish, encoded))
            else:
                additions.append(encoded)
        if additions:
            append_entry(text, items, end, (',' + newline + '    ').join(additions), newline, edits)
    font = font_edit(text, clean, settings, root_items, newline, edits)
    if font:
        missing.append(font)
    if missing:
        append_entry(text, root_items, root_end, (',' + newline + '    ').join(missing), newline, edits)
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    # Validate the result before creating a backup or changing anything.
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


def prompt_font_face(settings):
    """Return the prompt font for the default profile face, or None when already set."""
    defaults = settings.get('profiles', {})
    defaults = defaults.get('defaults', {}) if isinstance(defaults, dict) else None
    if not isinstance(defaults, dict):
        return None  # The legacy profiles array has no defaults to change.
    font = defaults.get('font', {})
    face = font.get('face') if isinstance(font, dict) else None
    return None if face == PROMPT_FONT else PROMPT_FONT


def font_edit(text, clean, settings, root_items, newline, edits):
    """Set the default face to the prompt font; return a missing root property."""
    face = prompt_font_face(settings)
    items, end = root_items, None
    path = ('profiles', 'defaults', 'font', 'face')
    for depth, key in enumerate(path if face else ()):
        found = [item for item in items if item[0] == key]
        if not found:
            value = face
            for name in reversed(path[depth + 1:]):
                value = {name: value}
            encoded = json.dumps(key) + ': ' + json.dumps(value, ensure_ascii=False)
            if end is None:
                return encoded
            append_entry(text, items, end, encoded, newline, edits)
            break
        _, value, begin, finish = found[0]
        if key == 'face':
            edits.append((begin, finish, json.dumps(face, ensure_ascii=False)))
        if key == 'face' or not isinstance(value, dict):
            break
        items, end = members(clean, begin, object_mode=True)
    return None


def append_entry(text, items, end, encoded, newline, edits):
    prefix = ''
    if items:
        last_end = items[-1][3]
        # A comma may already be present before an end-of-array comment.
        if not clean_jsonc(text[last_end:end]).strip().startswith(','):
            if last_end == end:
                prefix = ','
            else:
                edits.append((last_end, last_end, ','))
    edits.append((end, end, prefix + newline + '    ' + encoded + newline))


def save(path, original, updated, label):
    """Back up and replace settings read as original; return the backup path."""
    encoding = 'utf-8-sig' if original.startswith(b'\xef\xbb\xbf') else 'utf-8'
    backup = path.with_name(path.name + '.dalftui-' + uuid.uuid4().hex + '.bak')
    # Check for edits made while setup was reading the settings.
    if path.read_bytes() != original:
        raise ValueError(f'{label} settings changed during setup. Rerun setup.')
    shutil.copyfile(path, backup)
    path.write_bytes(updated.encode(encoding))
    return backup


def configure(path, commandline, pwsh=None):
    original = path.read_bytes()
    text = original.decode('utf-8-sig')
    updated = updated_settings(text, commandline, pwsh)
    if updated == text:
        print(f'Terminal shortcut already configured: {path}')
        return
    backup = save(path, original, updated, 'Terminal')
    print(f'Terminal backup: {backup}')
    print(f'Ctrl+Shift+F2 opens dssh in a new tab: {path}')
    print('Ctrl+Shift+F3 opens the current folder in VS Code (local PowerShell or remote tmux).')
    print(f'Default profile font: {PROMPT_FONT}')
    if pwsh:
        print(f'PowerShell 7 uses ClearType; elevated copy: {ADMIN_NAME}')


def vscode_settings(text):
    """Set the VS Code terminal font, replacing the effective top-level values."""
    newline = '\r\n' if '\r\n' in text else '\n'
    if not clean_jsonc(text).strip():  # VS Code reads an empty file as no settings.
        text = (text + newline if text.strip() else '') + '{}'
    clean = clean_jsonc(text)
    settings = json.loads(clean)  # VS Code accepts duplicate keys; the last one wins.
    if not isinstance(settings, dict):
        raise ValueError('VS Code settings must be a JSON object.')
    edits = []
    missing = []
    items, end = members(clean, skip_space(clean, 0), object_mode=True)
    for key, value in VSCODE_SETTINGS.items():
        found = [item for item in items if item[0] == key]
        if not found:
            missing.append(json.dumps(key) + ': ' + json.dumps(value))
        elif found[-1][1] != value:
            edits.append((found[-1][2], found[-1][3], json.dumps(value)))
    if missing:
        append_entry(text, items, end, (',' + newline + '    ').join(missing), newline, edits)
    for begin, finish, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[finish:]
    json.loads(clean_jsonc(text))
    return text


def configure_vscode(path):
    original = path.read_bytes() if path.exists() else None
    text = (original or b'').decode('utf-8-sig')
    updated = vscode_settings(text)
    if updated == text:
        print(f'VS Code terminal font already set: {path}')
        return
    if original is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:  # Never replace a file created meanwhile.
            stream.write(updated.encode())
        print(f'VS Code settings created: {path}')
    else:
        print(f'VS Code backup: {save(path, original, updated, "VS Code")}')
    print(f'VS Code terminal font: {PROMPT_FONT}, size 12')


def settings_paths(local_app_data):
    if not local_app_data:
        return []
    root = Path(local_app_data)
    paths = [root / 'Packages' / f'Microsoft.WindowsTerminal{channel}_8wekyb3d8bbwe' /
             'LocalState' / 'settings.json' for channel in ('', 'Preview', 'Canary')]
    paths.append(root / 'Microsoft' / 'Windows Terminal' / 'settings.json')
    return [path for path in paths if path.is_file()]


def main():
    # Redirected output in Windows PowerShell 5.1 may use an ANSI code page.
    # A Unicode checkout path must not turn a successful install into an error.
    sys.stdout.reconfigure(errors='backslashreplace')
    sys.stderr.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shell', required=True)
    parser.add_argument('--settings', action='append', type=Path)
    parser.add_argument('--pwsh', help='PowerShell 7 path for the Terminal profiles')
    parser.add_argument('--vscode-settings', type=Path, help='VS Code settings.json to set the terminal font in')
    args = parser.parse_args()
    status = 0
    if args.vscode_settings:
        try:
            configure_vscode(args.vscode_settings)
        except (OSError, UnicodeError, ValueError) as error:
            print(f'VS Code font setup failed: {error}', file=sys.stderr)
            status = 1
    launcher = CHECKOUT_ROOT / 'bin/ssh-tab.ps1'
    commandline = subprocess.list2cmdline([
        args.shell, '-NoLogo', '-NoProfile', '-File', str(launcher)])
    pwsh = subprocess.list2cmdline([args.pwsh]) if args.pwsh else None
    if not pwsh:
        print('PowerShell 7 not found; Windows Terminal PowerShell 7 profiles were not added.')
    paths = args.settings or settings_paths(os.environ.get('LOCALAPPDATA', ''))
    if not paths:
        print('Windows Terminal settings not found. Open Terminal once, then rerun setup. For a portable installation use -TerminalSettingsPath PATH. dssh remains available in PowerShell.')
        return status
    try:
        for path in dict.fromkeys(paths):
            configure(path, commandline, pwsh)
    except (OSError, UnicodeError, ValueError) as error:
        print(f'Terminal shortcut setup failed: {error}', file=sys.stderr)
        return 1
    return status


if __name__ == '__main__':
    raise SystemExit(main())
