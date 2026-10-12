"""Set the Terminal defaults, VS Code font and PowerShell 7 profiles, preserving other settings."""
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
# Ctrl+Shift+F2/F3 actions installed by earlier versions; setup removes them.
ACTION_ID = 'User.DalftuiSshPicker'
EDITOR_ACTION_ID = 'User.DalftuiOpenFolderInCode'
PROMPT_FONT = 'Hack Nerd Font'
# Also applied by ./install on Linux desktops and macOS.
VSCODE_SETTINGS = {'terminal.integrated.fontFamily': PROMPT_FONT, 'terminal.integrated.fontSize': 12}
# Windows uses FiraCode; setup replaces the PROMPT_FONT that earlier Windows versions set.
WINDOWS_FONT = 'FiraCode Nerd Font Mono'
WINDOWS_VSCODE_SETTINGS = {**VSCODE_SETTINGS, 'terminal.integrated.fontFamily': WINDOWS_FONT}
# The values uninstall treats as dalftui's, including the earlier Windows font.
WINDOWS_VSCODE_VALUES = {'terminal.integrated.fontFamily': (WINDOWS_FONT, PROMPT_FONT),
                         'terminal.integrated.fontSize': (12,)}
TERMINAL_DEFAULTS = {'font': {'face': WINDOWS_FONT}, 'cursorShape': 'bar',
                     'padding': '8, 8, 8, 8', 'bellStyle': 'none'}
# Windows Terminal's own PowerShell 7 profile, and a dalftui-owned elevated copy.
PWSH_GUID = '{574e775e-4f2a-5b96-ac1e-a2962a402336}'
PWSH_SOURCE = 'Windows.Terminal.PowershellCore'
ADMIN_GUID = '{267e52e6-0ec9-495c-a8b0-e4437770bc55}'
ADMIN_NAME = 'Windows PowerShell 7 (Admin)'
# Profiles from the old setup gist, replaced by the two above.
GIST_NAMES = ('Windows PowerShell 7', 'Windows PowerShell 7 (Administrator)')
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


def updated_settings(text, pwsh=None):
    text = default_settings(removed_actions(text))
    return profile_settings(removed_gist_profiles(text), pwsh) if pwsh else text


def runs_pwsh(commandline):
    """Return whether a profile command line starts pwsh.exe, quoted or not."""
    if not isinstance(commandline, str):
        return False
    commandline = commandline.strip()
    if commandline.startswith('"'):
        program = commandline[1:].partition('"')[0]
    else:
        program = (commandline.split() or [''])[0]
        if re.search(r'[\\/]', program):
            # Like CreateProcess, an unquoted path may contain spaces: the shortest prefix
            # ending in .exe, such as C:\Program Files\PowerShell\7\pwsh.exe.
            program = re.match(r'(?i)\S*?(?:\s+\S+?)*?\.exe(?=\s|$)|\S*', commandline).group()
    return re.split(r'[\\/]', program)[-1].lower() == 'pwsh.exe'


def is_gist_profile(entry):
    # Exact names and no source: Terminal's generated profiles and dalftui's never match.
    return (isinstance(entry, dict) and entry.get('name') in GIST_NAMES and 'source' not in entry
            and str(entry.get('guid')).lower() not in (PWSH_GUID, ADMIN_GUID)
            and runs_pwsh(entry.get('commandline')))


def gist_profiles(settings):
    profiles = settings.get('profiles')
    entries = profiles.get('list') if isinstance(profiles, dict) else None
    return [entry for entry in entries if is_gist_profile(entry)] if isinstance(entries, list) else []


def removed_gist_profiles(text):
    """Remove the old gist's PowerShell 7 profiles in favor of Terminal's, which also becomes
    the default in place of a removed one."""
    removed = gist_profiles(json.loads(clean_jsonc(text), object_pairs_hook=unique_object))
    if not removed:
        return text
    text = remove_matching(text, ('profiles', 'list'), lambda item: is_gist_profile(item[1]))
    clean = clean_jsonc(text)
    remaining = json.loads(clean, object_pairs_hook=unique_object)['profiles']['list']
    names = {entry.get('name') for entry in remaining if isinstance(entry, dict)}
    # Terminal accepts a GUID, or a name, which may still match a remaining profile.
    guids = {str(entry.get('guid')).lower() for entry in removed}
    gone = {entry['name'] for entry in removed} - names
    for name, value, begin, finish in container_items(clean, ()):
        if name == 'defaultProfile' and isinstance(value, str) and (value.lower() in guids or value in gone):
            text = text[:begin] + json.dumps(PWSH_GUID) + text[finish:]
    # Show Terminal's profile again if it was hidden, or its source disabled, as a duplicate.
    text = remove_matching(text, ('disabledProfileSources',), lambda item: item[1] == PWSH_SOURCE)
    for number, item in enumerate(container_items(clean_jsonc(text), ('profiles', 'list')) or []):
        if has_guid(item, PWSH_GUID):
            text = remove_matching(text, ('profiles', 'list', number),
                                   lambda member: member[0] == 'hidden' and member[1] is True)
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


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
    stub = {'guid': PWSH_GUID, 'source': PWSH_SOURCE}
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
            append_entry(text, items, end, additions, newline, edits)
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


def default_settings(text):
    """Set dalftui's profiles.defaults values, replacing other values of the same keys."""
    clean = clean_jsonc(text)
    json.loads(clean, object_pairs_hook=unique_object)
    root_items, root_end = members(clean, skip_space(clean, 0), object_mode=True)
    edits = []
    newline = '\r\n' if '\r\n' in text else '\n'
    nested_edits(text, clean, (root_items, root_end), {'profiles': {'defaults': TERMINAL_DEFAULTS}},
                 newline, edits)
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    # Validate the result before creating a backup or changing anything.
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


def nested_edits(text, clean, container, wanted, newline, edits):
    """Add edits giving the object whose members() are container the wanted nested values."""
    items, end = container
    missing = []
    for key, value in wanted.items():
        found = [item for item in items if item[0] == key]
        if not found:
            missing.append(json.dumps(key) + ': ' + json.dumps(value, ensure_ascii=False))
        elif isinstance(value, dict):
            # The legacy profiles array, or another non-object, is left unchanged.
            if isinstance(found[0][1], dict):
                nested = members(clean, found[0][2], object_mode=True)
                nested_edits(text, clean, nested, value, newline, edits)
        elif found[0][1] != value:
            edits.append((found[0][2], found[0][3], json.dumps(value, ensure_ascii=False)))
    if missing:
        append_entry(text, items, end, missing, newline, edits)


def line_indent(text, index):
    """Return the whitespace before index on its line, or None when other text precedes it."""
    line = text.rfind('\n', 0, index) + 1
    return None if text[line:index].strip() else text[line:index]


def append_entry(text, items, end, entries, newline, edits):
    """Append encoded entries to the container closing at end, indented like their siblings."""
    entries = [entries] if isinstance(entries, str) else entries
    prefix = ''
    if items:
        last_end = items[-1][3]
        # A comma may already be present before an end-of-array comment.
        if not clean_jsonc(text[last_end:end]).strip().startswith(','):
            if last_end == end:
                prefix = ','
            else:
                edits.append((last_end, last_end, ','))
    closing = line_indent(text, end)
    if closing is None:  # The closing bracket follows other text on its line.
        indent = '    '
        edits.append((end, end, prefix + newline + indent + (',' + newline + indent).join(entries) + newline))
        return
    sibling = line_indent(text, item_start(without_comments(text), items[-1][2])) if items else None
    indent = closing + '    ' if sibling is None else sibling
    # Insert before the closing bracket's own indentation so it stays aligned.
    line = end - len(closing)
    edits.append((line, line, prefix + indent + (',' + newline + indent).join(entries) + newline))


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


def removed_actions(text):
    """Remove the actions and key bindings that earlier setup versions added."""
    if not isinstance(json.loads(clean_jsonc(text), object_pairs_hook=unique_object), dict):
        raise ValueError('Terminal settings must be a JSON object.')
    ids = (ACTION_ID, EDITOR_ACTION_ID)
    for name in ('actions', 'keybindings'):
        text = remove_matching(text, (name,), lambda item: isinstance(item[1], dict) and item[1].get('id') in ids)
    return text


def removed_settings(text):
    """Remove what setup added to Terminal settings, while it still holds dalftui's values."""
    text = removed_actions(text)
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
    # Earlier Windows versions set PROMPT_FONT.
    text = remove_matching(text, ('profiles', 'defaults', 'font'),
                           lambda item: item[0] == 'face' and item[1] in (WINDOWS_FONT, PROMPT_FONT))
    text = remove_matching(text, ('profiles', 'defaults'), lambda item: item[0] != 'font' and
                           item[0] in TERMINAL_DEFAULTS and item[1] == TERMINAL_DEFAULTS[item[0]])
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


def removed_vscode_settings(text, values=None):
    """Remove the effective VS Code terminal font values while they are dalftui's.

    values maps each key to the values that count as dalftui's, by default VSCODE_SETTINGS.
    """
    values = values or {key: (value,) for key, value in VSCODE_SETTINGS.items()}
    if not clean_jsonc(text).strip():
        return text
    if not isinstance(json.loads(clean_jsonc(text)), dict):
        raise ValueError('VS Code settings must be a JSON object.')
    for key, owned in values.items():
        clean = clean_jsonc(text)
        items = container_items(clean, ())
        found = [number for number, item in enumerate(items) if item[0] == key]
        if found and items[found[-1]][1] in owned:
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
            unconfigure(vscode, 'VS Code', lambda text: removed_vscode_settings(text, WINDOWS_VSCODE_VALUES),
                        dry_run)
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


def configure(path, pwsh=None):
    original = path.read_bytes()
    text = original.decode('utf-8-sig')
    updated = updated_settings(text, pwsh)
    if updated == text:
        print(f'Terminal already configured: {path}')
        return
    gist = gist_profiles(json.loads(clean_jsonc(text), object_pairs_hook=unique_object)) if pwsh else []
    backup = save(path, original, updated, 'Terminal')
    print(f'Terminal backup: {backup}')
    print(f'Terminal configured: {path}')
    print(f'Default profile font: {WINDOWS_FONT}; bar cursor, padding 8, no bell')
    if pwsh:
        print(f'PowerShell 7 uses ClearType; elevated copy: {ADMIN_NAME}')
    for entry in gist:
        print(f'Removed profile from an old setup: {entry["name"]}')


def vscode_settings(text, settings=None):
    """Set the VS Code terminal font (VSCODE_SETTINGS by default), replacing the effective top-level values."""
    newline = '\r\n' if '\r\n' in text else '\n'
    if not clean_jsonc(text).strip():  # VS Code reads an empty file as no settings.
        text = (text + newline if text.strip() else '') + '{}'
    clean = clean_jsonc(text)
    # VS Code accepts duplicate keys; the last one wins.
    if not isinstance(json.loads(clean), dict):
        raise ValueError('VS Code settings must be a JSON object.')
    edits = []
    missing = []
    items, end = members(clean, skip_space(clean, 0), object_mode=True)
    for key, value in (settings or VSCODE_SETTINGS).items():
        found = [item for item in items if item[0] == key]
        if not found:
            missing.append(json.dumps(key) + ': ' + json.dumps(value))
        elif found[-1][1] != value:
            edits.append((found[-1][2], found[-1][3], json.dumps(value)))
    if missing:
        append_entry(text, items, end, missing, newline, edits)
    for begin, finish, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[finish:]
    json.loads(clean_jsonc(text))
    return text


def configure_vscode(path):
    original = path.read_bytes() if path.exists() else None
    text = (original or b'').decode('utf-8-sig')
    updated = vscode_settings(text, WINDOWS_VSCODE_SETTINGS)
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
    print(f'VS Code terminal font: {WINDOWS_FONT}, size 12')


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
    parser.add_argument('--settings', action='append', type=Path)
    parser.add_argument('--pwsh', help='PowerShell 7 path for the Terminal profiles')
    parser.add_argument('--vscode-settings', type=Path, help='VS Code settings.json to set the terminal font in')
    parser.add_argument('--uninstall', action='store_true', help='Remove the settings that setup added')
    parser.add_argument('--dry-run', action='store_true', help='With --uninstall, show changes without writing files')
    args = parser.parse_args()
    if args.uninstall:
        return uninstall(args.settings or settings_paths(os.environ.get('LOCALAPPDATA', '')),
                         args.vscode_settings, args.dry_run)
    status = 0
    if args.vscode_settings:
        try:
            configure_vscode(args.vscode_settings)
        except (OSError, UnicodeError, ValueError) as error:
            print(f'VS Code font setup failed: {error}', file=sys.stderr)
            status = 1
    pwsh = subprocess.list2cmdline([args.pwsh]) if args.pwsh else None
    if not pwsh:
        print('PowerShell 7 not found; Windows Terminal PowerShell 7 profiles were not added.')
    paths = args.settings or settings_paths(os.environ.get('LOCALAPPDATA', ''))
    if not paths:
        print('Windows Terminal settings not found. Open Terminal once, then rerun setup. For a portable installation use -TerminalSettingsPath PATH. dssh remains available in PowerShell.')
        return status
    try:
        for path in dict.fromkeys(paths):
            configure(path, pwsh)
    except (OSError, UnicodeError, ValueError) as error:
        print(f'Terminal setup failed: {error}', file=sys.stderr)
        return 1
    return status


if __name__ == '__main__':
    raise SystemExit(main())
