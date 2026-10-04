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


def updated_settings(text, commandline):
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
    if missing:
        append_entry(text, root_items, root_end, (',' + newline + '    ').join(missing), newline, edits)
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    # Validate the result before creating a backup or changing anything.
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


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


def configure(path, commandline):
    original = path.read_bytes()
    text = original.decode('utf-8-sig')
    updated = updated_settings(text, commandline)
    if updated == text:
        print(f'Terminal shortcut already configured: {path}')
        return
    encoding = 'utf-8-sig' if original.startswith(b'\xef\xbb\xbf') else 'utf-8'
    backup = path.with_name(path.name + '.dalftui-' + uuid.uuid4().hex + '.bak')
    # Check for edits made while setup was reading the settings.
    if path.read_bytes() != original:
        raise ValueError('Terminal settings changed during setup. Rerun setup.')
    shutil.copyfile(path, backup)
    path.write_bytes(updated.encode(encoding))
    print(f'Terminal backup: {backup}')
    print(f'Ctrl+Shift+F2 opens dssh in a new tab: {path}')
    print('Ctrl+Shift+F3 opens the current folder in VS Code (local PowerShell or remote tmux).')


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
    args = parser.parse_args()
    launcher = CHECKOUT_ROOT / 'windows-terminal.ps1'
    commandline = subprocess.list2cmdline([
        args.shell, '-NoLogo', '-NoProfile', '-File', str(launcher)])
    paths = args.settings or settings_paths(os.environ.get('LOCALAPPDATA', ''))
    if not paths:
        print('Windows Terminal settings not found. Open Terminal once, then rerun setup. For a portable installation use -TerminalSettingsPath PATH. dssh remains available in PowerShell.')
        return 0
    try:
        for path in dict.fromkeys(paths):
            configure(path, commandline)
    except (OSError, UnicodeError, ValueError) as error:
        print(f'Terminal shortcut setup failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
