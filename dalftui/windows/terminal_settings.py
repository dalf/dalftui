"""Add the Ctrl+Shift+F2 SSH tab and set the Terminal defaults, VS Code font and PowerShell 7
profiles, preserving other settings."""
import argparse
import copy
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
# Terminal handles Ctrl+Shift+F2 before the running program: it opens a new tab with the picker.
ACTION_ID = 'User.DalftuiSshPicker'
SHORTCUT = 'ctrl+shift+f2'
# The Ctrl+Shift+F3 action installed by earlier versions; setup removes it.
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
# The profiles.defaults values that setup manages, by key path: (value, revision). Each
# settings file's record keeps the value setup wrote for each key and the value it replaced.
# To change a value, edit it: reruns move it only where the user kept the value setup wrote.
# Add a key with revision 1. Reruns and uninstall restore a dropped key, or remove it, where it
# still holds the value setup wrote. Incrementing a revision also replaces a value the user
# chose for that key, once, keeping the recorded value to restore.
DEFAULT_VALUES = {('font', 'face'): (WINDOWS_FONT, 1), ('cursorShape',): ('bar', 1),
                  ('padding',): ('8, 8, 8, 8', 1), ('bellStyle',): ('none', 1)}
# Values that installs before records set, used only while a settings file has no record.
PRE_RECORD_VALUES = {('font', 'face'): (WINDOWS_FONT, PROMPT_FONT), ('cursorShape',): ('bar',),
                     ('padding',): ('8, 8, 8, 8',), ('bellStyle',): ('none',)}
# What setup did to each Terminal settings file's defaults, kept next to it for reruns and uninstall.
RECORD_SUFFIX = '.dalftui-defaults.json'
RECORD_VERSION = 2
MISSING = object()
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


def normalized_key(key):
    return tuple(sorted(part.strip().lower() for part in key.split('+')))


def has_shortcut(entry, shortcut=SHORTCUT):
    keys = entry.get('keys', [])
    if isinstance(keys, str):
        keys = [keys]
    return isinstance(keys, list) and any(
        isinstance(key, str) and normalized_key(key) == normalized_key(shortcut)
        for key in keys)


class ShortcutSkipped(ValueError):
    """The Ctrl+Shift+F2 action was not added; the rest of Terminal setup still applies."""


def updated_settings(text, commandline, pwsh=None, skipped=None, record=None):
    """Return the updated settings. When the shortcut cannot be added, the reason is appended
    to skipped (a list) and the other settings are still updated. record is the
    default_settings record of this file, updated in place; None means a first run."""
    text = removed_actions(text)
    try:
        text = shortcut_settings(text, commandline)
    except ShortcutSkipped as reason:
        if skipped is not None:
            skipped.append(str(reason))
    text = default_settings(text, record)
    return profile_settings(removed_gist_profiles(text), pwsh) if pwsh else text


def updated_keys(keys):
    """Return inline action keys with SHORTCUT added, keeping the user's other keys."""
    if isinstance(keys, str):
        keys = [keys]
    if isinstance(keys, list) and keys and all(isinstance(key, str) for key in keys):
        return [*keys, SHORTCUT]
    return SHORTCUT


def shortcut_settings(text, commandline):
    """Add the Ctrl+Shift+F2 action that runs commandline in a new tab, or update it.

    Only dalftui's values change: other members, keys and comments in its entries are kept.
    Raises ShortcutSkipped, leaving the text unchanged, when the shortcut cannot be added.
    """
    clean = clean_jsonc(text)
    if not isinstance(json.loads(clean, object_pairs_hook=unique_object), dict):
        raise ValueError('Terminal settings must be a JSON object.')
    root_items, root_end = members(clean, skip_space(clean, 0), object_mode=True)
    properties = {name: (value, begin, finish) for name, value, begin, finish in root_items}
    arrays = {}
    for name in ('actions', 'keybindings'):
        if name not in properties:
            continue
        value, begin, finish = properties[name]
        if value is None:  # Like an empty array; replaced below.
            arrays[name] = (begin, finish)
            continue
        if not isinstance(value, list):
            raise ShortcutSkipped(f'Terminal {name} is not an array.')
        arrays[name] = members(clean, begin)
        if any(isinstance(entry, dict) and has_shortcut(entry) and entry.get('id') != ACTION_ID
               for entry in value):
            raise ShortcutSkipped('Ctrl+Shift+F2 already has a binding, which was kept. To use the '
                                  'SSH picker tab, remove that binding in Terminal settings, then rerun setup.')

    modern = 'keybindings' in properties
    command = {
        'action': 'newTab', 'commandline': commandline,
        'startingDirectory': '%USERPROFILE%', 'tabTitle': 'SSH',
        'suppressApplicationTitle': False, 'elevate': False,
    }
    action = {'id': ACTION_ID, 'name': 'SSH host picker (dssh)', 'command': command}
    desired = {'actions': action}
    if modern:
        desired['keybindings'] = {'id': ACTION_ID, 'keys': SHORTCUT}
    else:
        action['keys'] = SHORTCUT  # Inline keys, which older Terminal versions also read.
    edits = []
    missing = []
    newline = '\r\n' if '\r\n' in text else '\n'
    for name, entry in desired.items():
        if name not in arrays:
            missing.append(json.dumps(name) + ': ' + json.dumps([entry], ensure_ascii=False))
            continue
        if isinstance(arrays[name][0], int):  # null
            edits.append((*arrays[name], json.dumps([entry], ensure_ascii=False)))
            continue
        items, end = arrays[name]
        owned = [item for item in items if isinstance(item[1], dict) and item[1].get('id') == ACTION_ID]
        if name == 'keybindings':
            # Any binding of Ctrl+Shift+F2 to the action will do; other keys bound to it are the user's.
            if not any(has_shortcut(item[1]) for item in owned):
                append_entry(text, items, end, json.dumps(entry, ensure_ascii=False), newline, edits)
            continue
        if len(owned) > 1:
            raise ShortcutSkipped('Terminal actions has duplicate dalftui entries; remove the duplicates, '
                                  'then rerun setup.')
        if not owned:
            append_entry(text, items, end, json.dumps(entry, ensure_ascii=False), newline, edits)
            continue
        # Update only dalftui's values, such as the command line after moving the checkout.
        _, previous, begin, _ = owned[0]
        entry_items, entry_end = members(clean, begin, object_mode=True)
        wanted = {'name': action['name'], 'command': command}
        if not isinstance(previous.get('command', {}), dict):
            found = [item for item in entry_items if item[0] == 'command']
            edits.append((found[-1][2], found[-1][3], json.dumps(command, ensure_ascii=False)))
            del wanted['command']
        if not modern and not has_shortcut(previous):
            wanted['keys'] = updated_keys(previous.get('keys'))
        nested_edits(text, clean, (entry_items, entry_end), wanted, newline, edits)
    if missing:
        append_entry(text, root_items, root_end, missing, newline, edits)
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


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


def defaults_value(settings, key):
    """Return the profiles.defaults value at the key path, or MISSING."""
    value = settings.get('profiles') if isinstance(settings, dict) else None
    for part in ('defaults', *key):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def with_defaults(text, values):
    """Return text with the profiles.defaults values given by key path."""
    wanted = {}
    for key, value in values.items():
        target = wanted.setdefault('profiles', {}).setdefault('defaults', {})
        for part in key[:-1]:
            target = target.setdefault(part, {})
        target[key[-1]] = value
    clean = clean_jsonc(text)
    root_items, root_end = members(clean, skip_space(clean, 0), object_mode=True)
    edits = []
    nested_edits(text, clean, (root_items, root_end), wanted, '\r\n' if '\r\n' in text else '\n', edits)
    for begin, end, replacement in sorted(edits, reverse=True):
        text = text[:begin] + replacement + text[end:]
    # Validate the result before creating a backup or changing anything.
    json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    return text


def recorded_keys(record, settings):
    """Return the record's entries by dotted key path, converting the first format in place.

    That format listed the keys set ('applied') and the values they replaced ('previous'),
    but not the values written: the current value counts when it is dalftui's.
    """
    if 'keys' not in record:
        previous = record.get('previous', {})
        keys = {}
        for name in record.get('applied', []):
            key = tuple(name.split('.'))
            known = (*DEFAULT_VALUES.get(key, ())[:1], *PRE_RECORD_VALUES.get(key, ()))
            if not known:
                continue
            current = defaults_value(settings, key)
            keys[name] = {'written': current if current in known else known[0], 'revision': 1}
            if name in previous:
                keys[name]['previous'] = previous[name]
        record.clear()
        record.update(version=RECORD_VERSION, keys=keys)
    return record['keys']


def restored_defaults(text, settings, entries):
    """Restore the value each recorded key replaced, or remove the key, while it holds the
    value setup wrote."""
    for name, entry in entries.items():
        key = tuple(name.split('.'))
        if defaults_value(settings, key) != entry['written']:
            continue  # Changed by the user.
        previous = entry.get('previous', MISSING)
        if previous is MISSING or isinstance(previous, dict):  # with_defaults merges objects.
            text = removed_default(text, key)
        if previous is not MISSING:
            text = with_defaults(text, {key: previous})
    return text


def removed_default(text, key):
    """Remove the profiles.defaults member at the key path, keeping its parent objects."""
    return remove_matching(text, ('profiles', 'defaults', *key[:-1]), lambda item: item[0] == key[-1])


def default_settings(text, record=None):
    """Set dalftui's profiles.defaults values, keeping the values the user chose.

    record, updated in place, holds for each key the value setup wrote ('written'), the value
    it replaced, if any ('previous'), and the DEFAULT_VALUES revision ('revision'). A key that
    still holds the written value follows DEFAULT_VALUES; a missing key is set again; a value
    the user chose is kept unless the revision has increased since.
    """
    record = {} if record is None else record
    pre_record = not record
    settings = json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    entries = recorded_keys(record, settings)
    dropped = {name: entries.pop(name) for name in list(entries) if tuple(name.split('.')) not in DEFAULT_VALUES}
    text = restored_defaults(text, settings, dropped)
    wanted, pending = {}, {}
    for key, (value, revision) in DEFAULT_VALUES.items():
        name = '.'.join(key)
        current = defaults_value(settings, key)
        entry = entries.get(name)
        if entry is None:
            entry = {}
            # Once records exist, a key without one was dropped or never set: the value is the user's.
            if current not in (MISSING, value, *(PRE_RECORD_VALUES.get(key, ()) if pre_record else ())):
                entry['previous'] = current
        elif current not in (MISSING, value, entry['written']) and revision <= entry['revision']:
            continue  # Changed by the user.
        pending[name] = {**entry, 'written': value, 'revision': revision}
        if current != value:
            wanted[key] = value
    text = with_defaults(text, wanted)
    # Under a profiles, defaults or font that is not an object, nothing was set: record only what was.
    updated = json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    entries.update((name, entry) for name, entry in pending.items()
                   if defaults_value(updated, tuple(name.split('.'))) == entry['written'])
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


def removed_actions(text, ids=(EDITOR_ACTION_ID,)):
    """Remove dalftui's actions with these ids and their key bindings; by default, the
    Ctrl+Shift+F3 action that earlier versions added."""
    if not isinstance(json.loads(clean_jsonc(text), object_pairs_hook=unique_object), dict):
        raise ValueError('Terminal settings must be a JSON object.')
    for name in ('actions', 'keybindings'):
        text = remove_matching(text, (name,), lambda item: isinstance(item[1], dict) and item[1].get('id') in ids)
    return text


def removed_settings(text, record=None):
    """Remove what setup added to Terminal settings, while it still holds dalftui's values.

    Defaults that setup replaced, as listed in the default_settings record, are restored
    instead of removed. Without a record, a default is removed while it holds the current
    value or one that installs before records set.
    """
    settings = json.loads(clean_jsonc(text), object_pairs_hook=unique_object)
    entries = recorded_keys(copy.deepcopy(record or {}), settings)
    text = restored_defaults(text, settings, entries)
    # Once records exist, a key without one was dropped or never set: the value is the user's.
    for key in () if record else dict.fromkeys([*DEFAULT_VALUES, *PRE_RECORD_VALUES]):
        owned = (*DEFAULT_VALUES.get(key, ())[:1], *PRE_RECORD_VALUES.get(key, ()))
        if defaults_value(settings, key) in owned:
            text = removed_default(text, key)
    text = removed_actions(text, (ACTION_ID, EDITOR_ACTION_ID))
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
            record = read_record(path)
            unconfigure(path, 'Terminal', lambda text, record=record: removed_settings(text, record), dry_run)
            if not dry_run:
                record_path(path).unlink(missing_ok=True)
        except (OSError, UnicodeError, ValueError) as error:
            print(f'Terminal settings were not changed: {error}', file=sys.stderr)
            status = 1
    return status


def record_path(path):
    return path.with_name(path.name + RECORD_SUFFIX)


def read_record(path):
    """Return the default_settings record kept for a Terminal settings file; {} when there is none."""
    try:
        record = json.loads(record_path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {}
    except ValueError:
        record = None
    if isinstance(record, dict) and 'version' in record:
        entries = record.get('keys')
        valid = (record['version'] == RECORD_VERSION and isinstance(entries, dict) and all(
            isinstance(entry, dict) and 'written' in entry and isinstance(entry.get('revision'), int)
            for entry in entries.values()))
    else:  # The first format, without a version.
        valid = (isinstance(record, dict) and isinstance(record.get('previous', {}), dict)
                 and isinstance(record.get('applied', []), list)
                 and all(isinstance(name, str) for name in record.get('applied', [])))
    if not valid:
        print(f'Ignoring an unreadable {record_path(path).name}; earlier Terminal defaults are '
              f'in {path.name}.dalftui-*.bak backups.', file=sys.stderr)
        return {}
    return record


def write_record(path, record):
    """Replace the record in one step, so that a failed write keeps the earlier one."""
    target = record_path(path)
    pending = target.with_name(target.name + '.tmp')
    try:
        pending.write_text(json.dumps(record, indent=4, ensure_ascii=False) + '\n', encoding='utf-8')
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)


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
    """Configure one Terminal settings file.

    A Ctrl+Shift+F2 binding of the user's own is reported and kept, without failing setup:
    it would otherwise fail on every rerun while the user keeps that binding.
    """
    original = path.read_bytes()
    text = original.decode('utf-8-sig')
    skipped = []
    record = read_record(path)
    recorded = copy.deepcopy(record)
    updated = updated_settings(text, commandline, pwsh, skipped, record)
    for reason in skipped:
        print(f'Ctrl+Shift+F2 was not added to {path}: {reason}', file=sys.stderr)
    if updated == text:
        if record != recorded:
            write_record(path, record)
        print(f'Terminal already configured: {path}')
        return
    gist = gist_profiles(json.loads(clean_jsonc(text), object_pairs_hook=unique_object)) if pwsh else []
    backup = save(path, original, updated, 'Terminal')
    try:
        write_record(path, record)
    except OSError:
        # Without the record, the next run would take the values setup wrote for the user's own.
        path.write_bytes(original)
        raise
    print(f'Terminal backup: {backup}')
    print(f'Terminal configured: {path}')
    if not skipped:
        print('Ctrl+Shift+F2 opens the SSH picker (dssh) in a new tab.')
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
    parser.add_argument('--shell', help='PowerShell that runs the Ctrl+Shift+F2 tab; required without --uninstall')
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
    # Terminal starts this command line itself; cmd.exe never parses it. Like install.cmd,
    # the bypass applies only to this process, so the tab starts under the default
    # Restricted policy too.
    commandline = subprocess.list2cmdline([
        args.shell, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', str(CHECKOUT_ROOT / 'bin/ssh-tab.ps1')])
    pwsh = subprocess.list2cmdline([args.pwsh]) if args.pwsh else None
    if not pwsh:
        print('PowerShell 7 not found; Windows Terminal PowerShell 7 profiles were not added.')
    paths = args.settings or settings_paths(os.environ.get('LOCALAPPDATA', ''))
    if not paths:
        print('Windows Terminal settings not found. Open Terminal once, then rerun setup. For a portable installation use -TerminalSettingsPath PATH. dssh remains available in PowerShell.')
        return status
    # A problem in one installation, such as Terminal Preview, must not block the others.
    for path in dict.fromkeys(paths):
        try:
            configure(path, commandline, pwsh)
        except (OSError, UnicodeError, ValueError) as error:
            print(f'Terminal setup failed: {path}: {error}', file=sys.stderr)
            status = 1
    return status


if __name__ == '__main__':
    raise SystemExit(main())
