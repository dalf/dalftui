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


def without_comments(text):
    # Keep character offsets so edits preserve comments and unrelated formatting.
    def comments(match):
        part = match.group()
        return part if part.startswith('"') else re.sub(r'[^\r\n]', ' ', part)
    return JSONC_PARTS.sub(comments, text)


def clean_jsonc(text):
    return TRAILING_COMMAS.sub(lambda m: m.group(1) or ' ', without_comments(text))


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


def item_start(clean, begin):
    """Return where the member whose value starts at begin starts, including its key."""
    index = begin - 1
    while clean[index].isspace():
        index -= 1
    if clean[index] != ':':
        return begin  # An array element.
    index -= 1
    while clean[index].isspace():
        index -= 1
    index -= 1  # Before the key's closing quote; quotes inside the key are escaped.
    while True:
        slashes = 0
        while clean[index - 1 - slashes] == '\\':
            slashes += 1
        if clean[index] == '"' and slashes % 2 == 0:
            return index
        index -= 1


def remove_item(text, items, index):
    """Remove items[index] from a members() list, keeping comments and other items."""
    bare = without_comments(text)  # Unlike clean_jsonc, keeps trailing commas.
    begin, finish = item_start(bare, items[index][2]), items[index][3]
    comma = None
    after = skip_space(bare, finish)
    if bare[after] == ',':
        finish = after + 1
    elif index:
        comma = bare.rindex(',', items[index - 1][3], begin)
    # Drop the whole line when the item is alone on it.
    line = text.rfind('\n', 0, begin) + 1
    end = text.find('\n', finish)
    end = len(text) if end < 0 else end
    if not text[line:begin].strip() and not text[finish:end].strip():
        begin, finish = line, min(end + 1, len(text))
    text = text[:begin] + text[finish:]
    if comma is not None:
        text = text[:comma] + text[comma + 1:]
    return text


def container_items(clean, path):
    """Return members() of the object or array at path (keys or list indexes), or None."""
    begin, value = skip_space(clean, 0), True
    items = None
    for key in (None, *path):
        if key is not None:
            found = [item for number, item in enumerate(items)
                     if (number == key if isinstance(key, int) else item[0] == key)]
            if not found:
                return None
            _, value, begin, _ = found[-1]  # VS Code uses the last duplicate key.
        if not isinstance(value, (dict, list)) and key is not None:
            return None
        items, _ = members(clean, begin, object_mode=key is None or isinstance(value, dict))
    return items


def remove_matching(text, path, match):
    """Remove every item of the container at path for which match(item) is true."""
    while True:
        clean = clean_jsonc(text)
        items = container_items(clean, path) or []
        index = next((number for number, item in enumerate(items) if match(item)), None)
        if index is None:
            return text
        text = remove_item(text, items, index)


def has_guid(item, guid):
    return isinstance(item[1], dict) and str(item[1].get('guid')).lower() == guid


def removed_settings(text):
    """Remove what setup added to Terminal settings, while it still holds dalftui's values."""
    if not isinstance(json.loads(clean_jsonc(text), object_pairs_hook=unique_object), dict):
        raise ValueError('Terminal settings must be a JSON object.')
    ids = (ACTION_ID, EDITOR_ACTION_ID)
    for name in ('actions', 'keybindings'):
        text = remove_matching(text, (name,), lambda item: isinstance(item[1], dict) and item[1].get('id') in ids)
    profiles = ('profiles', 'list')
    text = remove_matching(text, profiles, lambda item: has_guid(item, ADMIN_GUID))
    # Terminal regenerates its own stub; keep one that has other settings.
    created = {'guid', 'source', 'antialiasingMode'}
    text = remove_matching(text, profiles, lambda item: has_guid(item, PWSH_GUID) and set(item[1]) == created
                           and item[1]['antialiasingMode'] == 'cleartype')
    for number, item in enumerate(container_items(clean_jsonc(text), profiles) or []):
        if has_guid(item, PWSH_GUID):
            text = remove_matching(text, (*profiles, number),
                                   lambda member: member[0] == 'antialiasingMode' and member[1] == 'cleartype')
    text = remove_matching(text, ('profiles', 'defaults', 'font'),
                           lambda item: item[0] == 'face' and item[1] == PROMPT_FONT)
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


def removed_vscode_settings(text):
    """Remove the effective VS Code terminal font values while they are dalftui's."""
    if not clean_jsonc(text).strip():
        return text
    if not isinstance(json.loads(clean_jsonc(text)), dict):
        raise ValueError('VS Code settings must be a JSON object.')
    for key, value in VSCODE_SETTINGS.items():
        clean = clean_jsonc(text)
        items = container_items(clean, ())
        found = [number for number, item in enumerate(items) if item[0] == key]
        if found and items[found[-1]][1] == value:
            text = remove_item(text, items, found[-1])
    json.loads(clean_jsonc(text))
    return text


def unconfigure(path, label, remove, dry_run):
    """Remove dalftui's settings from one file; return whether anything changed."""
    original = path.read_bytes()
    text = original.decode('utf-8-sig')
    updated = remove(text)
    if updated == text:
        print(f'No dalftui {label} settings: {path}')
        return False
    if dry_run:
        print(f'Back up and remove dalftui {label} settings: {path}')
        return True
    print(f'{label} backup: {save(path, original, updated, label)}')
    print(f'Removed dalftui {label} settings: {path}')
    print(f'Earlier values, if any, are in {path.name}.dalftui-*.bak next to it.')
    return True


def uninstall(paths, vscode, dry_run):
    status = 0
    if vscode and vscode.is_file():
        try:
            unconfigure(vscode, 'VS Code', removed_vscode_settings, dry_run)
        except (OSError, UnicodeError, ValueError) as error:
            print(f'VS Code settings were not changed: {error}', file=sys.stderr)
            status = 1
    if not paths:
        print('Windows Terminal settings not found; Terminal was not checked. '
              'For a portable installation use -TerminalSettingsPath PATH.')
    for path in dict.fromkeys(paths):
        try:
            unconfigure(path, 'Terminal', removed_settings, dry_run)
        except (OSError, UnicodeError, ValueError) as error:
            print(f'Terminal settings were not changed: {error}', file=sys.stderr)
            status = 1
    return status


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
    parser.add_argument('--shell')
    parser.add_argument('--settings', action='append', type=Path)
    parser.add_argument('--pwsh', help='PowerShell 7 path for the Terminal profiles')
    parser.add_argument('--vscode-settings', type=Path, help='VS Code settings.json to set the terminal font in')
    parser.add_argument('--uninstall', action='store_true', help='Remove the settings that setup added')
    parser.add_argument('--dry-run', action='store_true', help='With --uninstall, show changes without writing files')
    args = parser.parse_args()
    if args.uninstall:
        return uninstall(args.settings or settings_paths(os.environ.get('LOCALAPPDATA', '')),
                         args.vscode_settings, args.dry_run)
    if not args.shell:
        parser.error('--shell is required')
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
