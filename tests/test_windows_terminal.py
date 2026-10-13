"""Terminal settings tests, runnable on Linux and native Windows."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dalftui.windows import terminal_settings as terminal

LAUNCHER = 'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "C:\\dalftui\\bin\\ssh-tab.ps1"'
SHELL = ('--shell', 'pwsh.exe')
# The Ctrl+Shift+F2/F3 entries that earlier versions installed, in the modern form.
# Setup keeps the Ctrl+Shift+F2 action (or restores it) and removes the F3 one.
LEGACY_ACTIONS = [
    {'id': terminal.ACTION_ID, 'name': 'SSH host picker (dssh)', 'command': {
        'action': 'newTab', 'commandline': 'powershell.exe -NoLogo -NoProfile -File "C:\\dalftui\\bin/ssh-tab.ps1"',
        'startingDirectory': '%USERPROFILE%', 'tabTitle': 'SSH', 'suppressApplicationTitle': False, 'elevate': False}},
    {'id': terminal.EDITOR_ACTION_ID, 'name': 'Open current folder in VS Code',
     'command': {'action': 'sendInput', 'input': '\x02\x1bOR'}},
]
LEGACY_KEYBINDINGS = [{'id': terminal.ACTION_ID, 'keys': 'ctrl+shift+f2'},
                      {'id': terminal.EDITOR_ACTION_ID, 'keys': 'ctrl+shift+f3'}]
TERMINAL_DEFAULTS = {'font': {'face': terminal.WINDOWS_FONT}, 'cursorShape': 'bar',
                     'padding': '8, 8, 8, 8', 'bellStyle': 'none'}


class TerminalSetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-terminal-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / 'settings.json'

    def settings(self, text):
        return json.loads(terminal.clean_jsonc(text))

    def test_preserves_comments_trailing_commas_unicode_and_existing_settings(self):
        personal = '''{
    // Keep my defaults and shortcuts.
    "defaultProfile": "wsl-guid",
    "profiles": {"defaults": {"font": {"face": "Cascadia Code"}}, "list": []},
    "theme": "\u00e9 // not a comment",
    "url": "https://example.org/*not a comment*/",
    "actions": [
        {"command": "copy", "keys": "ctrl+shift+c"}, // my binding
    ], /* leave this here */
}'''
        updated = terminal.updated_settings(personal, LAUNCHER)
        for line in ('// Keep my defaults and shortcuts.', '// my binding', '/* leave this here */',
                     '"theme": "\u00e9 // not a comment"', '"url": "https://example.org/*not a comment*/"'):
            self.assertIn(line, updated)
        result = self.settings(updated)
        self.assertEqual(result['defaultProfile'], 'wsl-guid')
        self.assertEqual(result['actions'][0], {'command': 'copy', 'keys': 'ctrl+shift+c'})
        # Without a keybindings array, the action carries its keys, as older Terminal versions expect.
        action = result['actions'][1]
        self.assertEqual(action['keys'], 'ctrl+shift+f2')
        self.assertEqual(action['command']['action'], 'newTab')
        self.assertEqual(action['command']['commandline'], LAUNCHER)
        self.assertNotIn('profile', action['command'])
        self.assertFalse(action['command']['suppressApplicationTitle'])
        self.assertEqual(len(result['actions']), 2)
        self.assertNotIn('keybindings', result)

    def test_default_face_uses_windows_font_once(self):
        for profiles in ('{"defaults": {"font": {"face": "Cascadia Code"}}, "list": []}',
                         '{"defaults": {"fontFace": "Consolas"}, "list": []}',
                         '{"defaults": {"font": {"size": 11}}, "list": []}',
                         '{"list": []}',
                         # Earlier Windows versions set Hack Nerd Font.
                         '{"defaults": {"font": {"face": "Hack Nerd Font"}}}'):
            with self.subTest(profiles=profiles):
                updated = terminal.updated_settings('{"profiles": ' + profiles + '}', LAUNCHER)
                face = self.settings(updated)['profiles']['defaults']['font']['face']
                self.assertEqual(face, 'FiraCode Nerd Font Mono')
                self.assertEqual(terminal.updated_settings(updated, LAUNCHER), updated)
        legacy = self.settings(terminal.updated_settings('{"profiles": []}', LAUNCHER))
        self.assertEqual(legacy['profiles'], [])

    def test_profile_defaults_are_set_once_keeping_other_defaults(self):
        expected = {'font': {'face': 'FiraCode Nerd Font Mono'}, 'cursorShape': 'bar',
                    'padding': '8, 8, 8, 8', 'bellStyle': 'none'}
        for personal in ('{}', '{"profiles": {}}', '{"profiles": {"defaults": {}}}',
                         '{"profiles": {"defaults": {"cursorShape": "filledBox", "padding": "0",'
                         ' "bellStyle": "audible", "opacity": 90, // mine\n}}}',
                         '{\r\n  "profiles": {\r\n    "defaults": {\r\n      "font": {"size": 11}\r\n    }\r\n  }\r\n}\r\n'):
            with self.subTest(personal=personal):
                updated = terminal.updated_settings(personal, LAUNCHER)
                defaults = self.settings(updated)['profiles']['defaults']
                self.assertEqual(defaults['font']['face'], expected['font']['face'])
                self.assertEqual({key: defaults[key] for key in expected if key != 'font'},
                                 {key: value for key, value in expected.items() if key != 'font'})
                if 'opacity' in personal:
                    self.assertEqual(defaults['opacity'], 90)
                    self.assertIn('// mine', updated)
                if 'size' in personal:
                    self.assertEqual(defaults['font']['size'], 11)
                    self.assertNotIn('\n', updated.replace('\r\n', ''))
                self.assertEqual(terminal.updated_settings(updated, LAUNCHER), updated)
        self.assertEqual(self.settings(terminal.updated_settings('{}', LAUNCHER))['profiles'], {'defaults': expected})

    def rerun(self, defaults, record):
        """Run default_settings on settings whose profiles.defaults are defaults; return the new ones."""
        text = json.dumps({'profiles': {'defaults': defaults}})
        return self.settings(terminal.default_settings(text, record))['profiles']['defaults']

    def installed_defaults(self):
        """Return profiles.defaults and the record after a first run over personal values."""
        record = {}
        defaults = self.rerun({'cursorShape': 'filledBox', 'padding': '0', 'opacity': 90}, record)
        return defaults, record

    def test_profile_defaults_record_what_setup_wrote_and_replaced(self):
        defaults, record = self.installed_defaults()
        self.assertEqual(defaults, {**TERMINAL_DEFAULTS, 'opacity': 90})
        self.assertEqual(record, {'version': 2, 'keys': {
            'font.face': {'written': terminal.WINDOWS_FONT, 'revision': 1},
            'cursorShape': {'written': 'bar', 'previous': 'filledBox', 'revision': 1},
            'padding': {'written': '8, 8, 8, 8', 'previous': '0', 'revision': 1},
            'bellStyle': {'written': 'none', 'revision': 1}}})
        # A value that installs before records set is dalftui's, not one to restore.
        record = {}
        self.assertEqual(self.rerun({'font': {'face': terminal.PROMPT_FONT}, 'bellStyle': 'none'}, record),
                         TERMINAL_DEFAULTS)
        self.assertEqual([name for name, entry in record['keys'].items() if 'previous' in entry], [])

    def test_profile_defaults_keep_values_changed_after_setup(self):
        defaults, record = self.installed_defaults()
        recorded = json.loads(json.dumps(record))
        # Changed in Terminal after setup: kept. Removed: set again.
        defaults.update(cursorShape='vintage', bellStyle='audible')
        del defaults['padding']
        self.assertEqual(self.rerun(defaults, record), {**TERMINAL_DEFAULTS, 'cursorShape': 'vintage',
                                                        'bellStyle': 'audible', 'opacity': 90})
        self.assertEqual(record, recorded)

    def test_profile_defaults_follow_dalftui_changes_to_untouched_values(self):
        defaults, record = self.installed_defaults()
        defaults['padding'] = '2'
        values = {**terminal.DEFAULT_VALUES, ('cursorShape',): ('vintage', 1), ('padding',): ('4', 1),
                  ('opacity',): (95, 1), ('useAcrylic',): (True, 1)}
        with patch.object(terminal, 'DEFAULT_VALUES', values):
            rerun = self.rerun(defaults, record)
            self.assertEqual(self.rerun(rerun, record), rerun)
        # The cursor still had dalftui's value; the user had chosen the padding. New keys are set.
        self.assertEqual(rerun, {**TERMINAL_DEFAULTS, 'cursorShape': 'vintage', 'padding': '2',
                                 'opacity': 95, 'useAcrylic': True})
        keys = record['keys']
        self.assertEqual(keys['cursorShape'], {'written': 'vintage', 'previous': 'filledBox', 'revision': 1})
        self.assertEqual(keys['padding'], {'written': '8, 8, 8, 8', 'previous': '0', 'revision': 1})
        self.assertEqual(keys['opacity'], {'written': 95, 'previous': 90, 'revision': 1})
        self.assertEqual(keys['useAcrylic'], {'written': True, 'revision': 1})

    def test_dropped_profile_defaults_are_restored_or_removed(self):
        defaults, record = self.installed_defaults()
        defaults['padding'] = '2'
        values = {('font', 'face'): terminal.DEFAULT_VALUES[('font', 'face')]}
        with patch.object(terminal, 'DEFAULT_VALUES', values):
            rerun = self.rerun(defaults, record)
        # Restored where setup's value remains; the user's padding is kept. bellStyle had no value.
        self.assertEqual(rerun, {'font': {'face': terminal.WINDOWS_FONT}, 'cursorShape': 'filledBox',
                                 'padding': '2', 'opacity': 90})
        self.assertEqual(list(record['keys']), ['font.face'])

    def test_uninstall_restores_or_removes_defaults_that_setup_no_longer_manages(self):
        defaults, record = self.installed_defaults()
        values = {**terminal.DEFAULT_VALUES, ('opacity',): (95, 1), ('useAcrylic',): (True, 1),
                  ('tabTitle',): ('dalftui', 1)}
        with patch.object(terminal, 'DEFAULT_VALUES', values):
            defaults = self.rerun(defaults, record)
        defaults['tabTitle'] = 'mine'
        removed = self.settings(terminal.removed_settings(json.dumps({'profiles': {'defaults': defaults}}),
                                                          record))['profiles']['defaults']
        self.assertEqual(removed, {'font': {}, 'cursorShape': 'filledBox', 'padding': '0', 'opacity': 90,
                                   'tabTitle': 'mine'})

    def test_increased_revision_replaces_the_user_value_once(self):
        defaults, record = self.installed_defaults()
        defaults['cursorShape'] = 'vintage'
        values = {**terminal.DEFAULT_VALUES, ('cursorShape',): ('bar', 2)}
        with patch.object(terminal, 'DEFAULT_VALUES', values):
            defaults = self.rerun(defaults, record)
            self.assertEqual(defaults['cursorShape'], 'bar')
            self.assertEqual(record['keys']['cursorShape'], {'written': 'bar', 'previous': 'filledBox', 'revision': 2})
            defaults['cursorShape'] = 'vintage'
            self.assertEqual(self.rerun(defaults, record)['cursorShape'], 'vintage')
        removed = self.settings(terminal.removed_settings(json.dumps({'profiles': {'defaults': defaults}}),
                                                          record))['profiles']['defaults']
        self.assertEqual(removed['cursorShape'], 'vintage')

    def test_first_record_format_is_migrated(self):
        def first_record():
            return {'applied': ['font.face', 'cursorShape', 'padding', 'bellStyle'],
                    'previous': {'cursorShape': 'filledBox', 'padding': '0'}}
        defaults = {'font': {'face': terminal.PROMPT_FONT}, 'cursorShape': 'vintage', 'bellStyle': 'none'}
        record = first_record()
        # The earlier dalftui font was setup's: it moves. The user's cursor stays; padding is set again.
        self.assertEqual(self.rerun(defaults, record), {**TERMINAL_DEFAULTS, 'cursorShape': 'vintage'})
        self.assertEqual(record, {'version': 2, 'keys': {
            'font.face': {'written': terminal.WINDOWS_FONT, 'revision': 1},
            'cursorShape': {'written': 'bar', 'previous': 'filledBox', 'revision': 1},
            'padding': {'written': '8, 8, 8, 8', 'previous': '0', 'revision': 1},
            'bellStyle': {'written': 'none', 'revision': 1}}})
        defaults.update(cursorShape='bar', padding='4')
        removed = self.settings(terminal.removed_settings(json.dumps({'profiles': {'defaults': defaults}}),
                                                          first_record()))['profiles']['defaults']
        self.assertEqual(removed, {'font': {}, 'cursorShape': 'filledBox', 'padding': '4'})

    def test_dropped_defaults_the_user_chose_are_kept_even_with_earlier_dalftui_values(self):
        record = {}
        defaults = self.rerun({}, record)
        with patch.object(terminal, 'DEFAULT_VALUES', {**terminal.DEFAULT_VALUES, ('cursorShape',): ('filledBox', 1)}):
            defaults = self.rerun(defaults, record)
        defaults.update(cursorShape='bar', font={'face': terminal.PROMPT_FONT})
        values = {key: value for key, value in terminal.DEFAULT_VALUES.items() if key == ('padding',)}
        with patch.object(terminal, 'DEFAULT_VALUES', values):
            defaults = self.rerun(defaults, record)
            self.assertEqual(list(record['keys']), ['padding'])
            removed = self.settings(terminal.removed_settings(json.dumps({'profiles': {'defaults': defaults}}),
                                                              record))['profiles']['defaults']
        # bellStyle, dropped while it held setup's value, was removed by the rerun.
        self.assertEqual(removed, {'font': {'face': terminal.PROMPT_FONT}, 'cursorShape': 'bar'})
        # Managed again, the value is the user's: setup records it to restore.
        self.assertEqual(self.rerun(defaults, record)['cursorShape'], 'bar')
        self.assertEqual(record['keys']['cursorShape'], {'written': 'bar', 'revision': 1})
        self.assertEqual(record['keys']['font.face'],
                         {'written': terminal.WINDOWS_FONT, 'previous': terminal.PROMPT_FONT, 'revision': 1})

    def test_defaults_that_cannot_be_set_are_not_recorded(self):
        for profiles in ({'defaults': None}, []):  # The legacy profiles array.
            with self.subTest(profiles=profiles):
                record = {}
                text = json.dumps({'profiles': profiles})
                self.assertEqual(terminal.default_settings(text, record), text)
                self.assertEqual(record, {'version': 2, 'keys': {}})
        record = {}
        defaults = self.rerun({'font': 'Consolas'}, record)
        self.assertEqual(defaults['font'], 'Consolas')
        self.assertEqual(list(record['keys']), ['cursorShape', 'padding', 'bellStyle'])
        # Fixed later, the font is set and the user's face recorded to restore.
        defaults = self.rerun({**defaults, 'font': {'face': 'Consolas'}}, record)
        self.assertEqual(defaults['font'], {'face': terminal.WINDOWS_FONT})
        self.assertEqual(record['keys']['font.face'],
                         {'written': terminal.WINDOWS_FONT, 'previous': 'Consolas', 'revision': 1})

    def test_added_entries_follow_sibling_indentation(self):
        personal = ('{\n    "profiles": \n    {\n        "defaults": \n        {\n            "font": \n'
                    '            {\n                "face": "Hack Nerd Font"\n            }\n        },\n'
                    '        "list": []\n    }\n}\n')
        self.assertEqual(terminal.default_settings(personal), (
            '{\n    "profiles": \n    {\n        "defaults": \n        {\n            "font": \n'
            '            {\n                "face": "FiraCode Nerd Font Mono"\n            },\n'
            '            "cursorShape": "bar",\n            "padding": "8, 8, 8, 8",\n'
            '            "bellStyle": "none"\n        },\n        "list": []\n    }\n}\n'))

    def test_picker_entries_follow_terminal_formatting(self):
        # Terminal writes its settings like this.
        personal = ('{\n    "actions": \n    [\n        {\n            "command": "find",\n'
                    '            "id": "User.find"\n        }\n    ],\n    "keybindings": \n    [\n'
                    '        {\n            "id": "User.find",\n            "keys": "ctrl+shift+f"\n        }\n'
                    '    ]\n}\n')
        updated = terminal.shortcut_settings(personal, LAUNCHER)
        self.assertIn('            "id": "User.find"\n        },\n        {"id": "User.DalftuiSshPicker", ', updated)
        self.assertIn('        },\n        {"id": "User.DalftuiSshPicker", "keys": "ctrl+shift+f2"}\n    ]\n}\n',
                      updated)
        self.assertEqual(terminal.shortcut_settings(updated, LAUNCHER), updated)

    def gist_settings(self, default, *extra):
        return json.dumps({'defaultProfile': default, 'profiles': {'list': [
            {'guid': '{7e1e3c38-0000-4000-8000-000000000001}', 'name': 'Windows PowerShell 7',
             'commandline': 'pwsh.exe', 'hidden': False},
            {'guid': '{7e1e3c38-0000-4000-8000-000000000002}', 'name': 'Windows PowerShell 7 (Administrator)',
             'commandline': '"C:\\Program Files\\PowerShell\\7\\pwsh.exe" -NoLogo', 'elevate': True},
            {'guid': '{7e1e3c38-0000-4000-8000-000000000003}', 'name': 'Windows PowerShell 7',
             'commandline': 'C:\\Program Files\\PowerShell\\7\\pwsh.exe'},
            *extra]}}, indent=4)

    def test_old_gist_profiles_are_replaced_and_default_follows(self):
        mine = {'guid': '{mine}', 'name': 'Mine'}
        for default in ('{7E1E3C38-0000-4000-8000-000000000001}', '{7e1e3c38-0000-4000-8000-000000000002}',
                        'Windows PowerShell 7', 'Windows PowerShell 7 (Administrator)', '{mine}', 'Mine'):
            with self.subTest(default=default):
                personal = self.gist_settings(default, mine).replace('"name": "Mine"', '"name": "Mine" // keep')
                installed = terminal.updated_settings(personal, LAUNCHER, 'pwsh.exe')
                self.assertIn('// keep', installed)
                result = self.settings(installed)
                self.assertEqual([entry.get('guid') for entry in result['profiles']['list']],
                                 ['{mine}', terminal.PWSH_GUID, terminal.ADMIN_GUID])
                moved = 'mine' not in default.lower()
                self.assertEqual(result['defaultProfile'], terminal.PWSH_GUID if moved else default)
                self.assertEqual(terminal.updated_settings(installed, LAUNCHER, 'pwsh.exe'), installed)
        # Without PowerShell 7, nothing replaces them.
        personal = self.gist_settings('Windows PowerShell 7')
        self.assertEqual(self.settings(terminal.updated_settings(personal, LAUNCHER))['profiles']['list'],
                         self.settings(personal)['profiles']['list'])

    def test_old_gist_profile_matching_is_narrow(self):
        kept = [{'guid': '{a}', 'name': 'Windows PowerShell 7', 'commandline': 'pwsh.exe', 'source': 'x'},
                {'guid': '{b}', 'name': 'windows powershell 7', 'commandline': 'pwsh.exe'},
                {'guid': '{c}', 'name': 'Windows PowerShell 7 (Administrator)', 'commandline': 'powershell.exe'},
                {'guid': '{d}', 'name': 'Windows PowerShell 7', 'commandline': 'C:\\tools\\mypwsh.exe'},
                {'guid': '{e}', 'name': 'Windows PowerShell 7'},
                {'guid': '{f}', 'name': 'Windows PowerShell 7 (Administrator)', 'commandline': 'cmd /c pwsh.exe'},
                {'guid': '{g}', 'name': 'Windows PowerShell 7',
                 'commandline': 'C:\\Windows\\System32\\cmd.exe /c C:\\x\\pwsh.exe'}]
        personal = self.gist_settings('Windows PowerShell 7', *kept)
        result = self.settings(terminal.updated_settings(personal, LAUNCHER, 'pwsh.exe'))
        self.assertEqual(result['profiles']['list'][:len(kept)], kept)
        self.assertEqual(len(result['profiles']['list']), len(kept) + 2)
        # A remaining profile with the default's name still resolves it.
        self.assertEqual(result['defaultProfile'], 'Windows PowerShell 7')
        self.assertTrue(terminal.runs_pwsh(' C:/tools/PWSH.EXE -NoLogo'))
        # Like CreateProcess, an unquoted path may contain spaces.
        self.assertTrue(terminal.runs_pwsh('C:\\Program Files\\PowerShell\\7\\pwsh.exe'))
        self.assertTrue(terminal.runs_pwsh('C:\\Program Files\\PowerShell\\7\\pwsh.exe -NoLogo'))
        self.assertTrue(terminal.runs_pwsh('%ProgramFiles%\\PowerShell\\7\\pwsh.exe'))
        self.assertFalse(terminal.runs_pwsh('C:\\Program Files\\tools\\mypwsh.exe'))
        self.assertFalse(terminal.runs_pwsh(None))

    def test_terminal_and_dalftui_profiles_are_never_old_gist_profiles(self):
        for guid in (terminal.PWSH_GUID, terminal.ADMIN_GUID.upper()):
            for name in terminal.GIST_NAMES:
                with self.subTest(guid=guid, name=name):
                    entry = {'guid': guid, 'name': name, 'commandline': 'pwsh.exe'}
                    self.assertFalse(terminal.is_gist_profile(entry))
                    personal = json.dumps({'defaultProfile': name, 'profiles': {'list': [entry]}})
                    result = self.settings(terminal.updated_settings(personal, LAUNCHER, 'pwsh.exe'))
                    self.assertIn(guid, [profile['guid'] for profile in result['profiles']['list']])
                    self.assertEqual(result['defaultProfile'], name)

    def test_old_gist_replacement_shows_terminal_profile_again(self):
        # Old gist users may have hidden Terminal's duplicate PowerShell 7 profile.
        stub = {'guid': terminal.PWSH_GUID.upper(), 'hidden': True, 'source': terminal.PWSH_SOURCE}
        personal = json.loads(self.gist_settings('{7e1e3c38-0000-4000-8000-000000000001}', stub))
        personal['disabledProfileSources'] = ['Windows.Terminal.Wsl', terminal.PWSH_SOURCE]
        installed = terminal.updated_settings(json.dumps(personal, indent=4), LAUNCHER, 'pwsh.exe')
        result = self.settings(installed)
        self.assertEqual(result['disabledProfileSources'], ['Windows.Terminal.Wsl'])
        shown = {'guid': stub['guid'], 'source': terminal.PWSH_SOURCE, 'antialiasingMode': 'cleartype'}
        self.assertEqual(result['profiles']['list'][0], shown)
        self.assertEqual(result['defaultProfile'], terminal.PWSH_GUID)
        self.assertEqual(terminal.updated_settings(installed, LAUNCHER, 'pwsh.exe'), installed)
        # Without old gist profiles, a hidden or disabled Terminal profile is left alone.
        hidden = json.dumps({'disabledProfileSources': [terminal.PWSH_SOURCE], 'profiles': {'list': [stub]}})
        result = self.settings(terminal.updated_settings(hidden, LAUNCHER, 'pwsh.exe'))
        self.assertIs(result['profiles']['list'][0]['hidden'], True)
        self.assertEqual(result['disabledProfileSources'], [terminal.PWSH_SOURCE])

    def test_cli_reports_removed_gist_profiles(self):
        self.path.write_text(self.gist_settings('Windows PowerShell 7'), encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'), *SHELL, '--settings',
                                 str(self.path), '--pwsh', 'pwsh.exe'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Removed profile from an old setup: Windows PowerShell 7 (Administrator)', result.stdout)
        self.assertEqual(self.settings(self.path.read_text(encoding='utf-8'))['defaultProfile'], terminal.PWSH_GUID)
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)

    def test_rerun_keeps_picker_removes_editor_action_and_keeps_personal_entries(self):
        copy = {'id': 'Personal.Copy', 'command': 'copy'}
        # Ctrl+Shift+F3 is free again for a binding of the user's own.
        mine = {'id': 'Personal.Mine', 'keys': 'ctrl+shift+f3'}
        inline = [dict(action, keys=binding['keys']) for action, binding in zip(LEGACY_ACTIONS, LEGACY_KEYBINDINGS)]
        rebound = {'id': terminal.ACTION_ID, 'keys': 'ctrl+alt+s'}
        picker = dict(LEGACY_ACTIONS[0], command=dict(LEGACY_ACTIONS[0]['command'], commandline=LAUNCHER))
        for old in ({'actions': [copy, *LEGACY_ACTIONS], 'keybindings': [*LEGACY_KEYBINDINGS, rebound, mine]},
                    {'actions': [*inline, copy, mine]}):
            with self.subTest(old=old):
                updated = terminal.updated_settings(json.dumps(old, indent=4), LAUNCHER)
                result = self.settings(updated)
                if 'keybindings' in old:
                    self.assertEqual(result['actions'], [copy, picker])
                    self.assertEqual(result['keybindings'], [LEGACY_KEYBINDINGS[0], rebound, mine])
                else:
                    self.assertEqual(result['actions'], [dict(picker, keys='ctrl+shift+f2'), copy, mine])
                self.assertEqual(terminal.updated_settings(updated, LAUNCHER), updated)

    def test_handles_empty_missing_arrays_and_compact_settings(self):
        for personal in ('{}', '{ /* comment */ }', '{"theme":"dark"}',
                         '{"actions":[]}', '{"actions":[{"command":"copy"}]}',
                         '{"keybindings":[]}', '{"actions":[],"keybindings":[],}',
                         '{"actions":[{"command":"copy"} // final comment\n]}'):
            with self.subTest(personal=personal):
                updated = terminal.updated_settings(personal, LAUNCHER)
                result = self.settings(updated)
                self.assertEqual([entry['id'] for entry in result['actions'] if 'id' in entry], [terminal.ACTION_ID])
                self.assertEqual(result['actions'][-1]['command']['commandline'], LAUNCHER)
                # Settings with a keybindings array use the modern form.
                modern = 'keybindings' in personal
                self.assertEqual(result.get('keybindings'),
                                 [{'id': terminal.ACTION_ID, 'keys': 'ctrl+shift+f2'}] if modern else None)
                self.assertEqual(result['actions'][-1].get('keys'), None if modern else 'ctrl+shift+f2')
                self.assertEqual(terminal.updated_settings(updated, LAUNCHER), updated)

    def test_reruns_are_idempotent_and_moved_checkout_updates_managed_action(self):
        first = terminal.updated_settings('{"actions":[],"keybindings":[]}', 'old-launcher')
        self.assertEqual(terminal.updated_settings(first, 'old-launcher'), first)
        result = self.settings(terminal.updated_settings(first, 'new-launcher'))
        self.assertEqual(len(result['actions']), 1)
        self.assertEqual(len(result['keybindings']), 1)
        self.assertEqual(result['actions'][0]['command']['commandline'], 'new-launcher')

    def test_ui_migration_and_additional_personal_shortcuts_do_not_duplicate_entries(self):
        # Terminal moves inline keys to the keybindings array when it saves its settings.
        actions = self.settings(terminal.updated_settings('{}', LAUNCHER))['actions']
        for action in actions:
            del action['keys']
        personal = json.dumps({'actions': actions, 'keybindings': [
            {'id': terminal.ACTION_ID, 'keys': 'ctrl+shift+f2'},
            {'id': terminal.ACTION_ID, 'keys': 'ctrl+alt+s'},
        ], 'profiles': {'defaults': TERMINAL_DEFAULTS}})
        self.assertEqual(terminal.updated_settings(personal, LAUNCHER), personal)

    def test_user_edits_to_dalftui_entries_are_kept(self):
        # Keys, members and comments the user added to dalftui's entries survive reruns.
        keys = ['ctrl+shift+f2', 'ctrl+alt+s']
        old = LEGACY_ACTIONS[0]
        legacy = ('{"actions": [{\n  "id": "User.DalftuiSshPicker", // mine\n  "keys": ' + json.dumps(keys) +
                  ',\n  "name": "Mine",\n  "command": ' + json.dumps(dict(old['command'], profile='Mine')) + '\n}]}')
        modern = json.dumps({'actions': [dict(old, keys='ctrl+alt+x')],
                             'keybindings': [{'id': terminal.ACTION_ID, 'keys': keys}]}, indent=4)
        for personal in (legacy, modern):
            with self.subTest(personal=personal):
                updated = terminal.shortcut_settings(personal, LAUNCHER)
                self.assertEqual(terminal.shortcut_settings(updated, LAUNCHER), updated)
                action = self.settings(updated)['actions'][0]
                self.assertEqual(action['command']['commandline'], LAUNCHER)
                if personal is legacy:
                    self.assertIn('// mine', updated)
                    self.assertEqual(action['keys'], keys)
                    self.assertEqual(action['command']['profile'], 'Mine')
                else:
                    self.assertEqual(action['keys'], 'ctrl+alt+x')
                    self.assertEqual(self.settings(updated)['keybindings'],
                                     [{'id': terminal.ACTION_ID, 'keys': keys}])
        # Without Ctrl+Shift+F2 among its inline keys, the action gets it as well.
        for keys, expected in (('ctrl+alt+s', ['ctrl+alt+s', 'ctrl+shift+f2']), (None, 'ctrl+shift+f2'),
                               (['ctrl+alt+s'], ['ctrl+alt+s', 'ctrl+shift+f2'])):
            with self.subTest(keys=keys):
                personal = json.dumps({'actions': [{'id': terminal.ACTION_ID, 'keys': keys, 'command': 'x'}]})
                action = self.settings(terminal.shortcut_settings(personal, LAUNCHER))['actions'][0]
                self.assertEqual(action['keys'], expected)
                self.assertEqual(action['command']['commandline'], LAUNCHER)

    def test_shortcut_conflicts_keep_the_binding_and_apply_other_settings(self):
        for key in ('ctrl+shift+f2', 'SHIFT+CTRL+F2', ['ctrl+v', 'ctrl+shift+f2']):
            for array in ('actions', 'keybindings'):
                # A null id is how Terminal unbinds a key.
                for owner in ('Personal.Action', None):
                    with self.subTest(key=key, array=array, owner=owner):
                        personal = json.dumps({array: [{'id': owner, 'keys': key}]})
                        with self.assertRaisesRegex(terminal.ShortcutSkipped, r'Ctrl\+Shift\+F2 already has a binding'):
                            terminal.shortcut_settings(personal, LAUNCHER)
                        skipped = []
                        result = self.settings(terminal.updated_settings(personal, LAUNCHER, None, skipped))
                        self.assertEqual(result[array], [{'id': owner, 'keys': key}])
                        self.assertEqual(len(result), 2)
                        self.assertEqual(result['profiles']['defaults'], TERMINAL_DEFAULTS)
                        self.assertEqual(len(skipped), 1)
        # Even next to dalftui's own entries from an earlier setup. Another Terminal installation,
        # such as Preview, is still configured.
        personal = json.dumps({'actions': LEGACY_ACTIONS, 'keybindings': [
            *LEGACY_KEYBINDINGS, {'id': 'Personal.Action', 'keys': 'ctrl+shift+f2'}]})
        self.path.write_text(personal, encoding='utf-8')
        preview = self.root / 'preview.json'
        preview.write_text('{}', encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'), *SHELL,
                                 '--settings', str(self.path), '--settings', str(preview)],
                                capture_output=True, text=True)
        # Only reported: setup would otherwise fail on every rerun while the binding stays.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'Ctrl+Shift+F2 was not added to {self.path}: Ctrl+Shift+F2 already has a binding',
                      result.stderr)
        stable = self.settings(self.path.read_text(encoding='utf-8'))
        # The earlier F3 entries are still removed.
        self.assertEqual(stable['keybindings'], [LEGACY_KEYBINDINGS[0], {'id': 'Personal.Action', 'keys': 'ctrl+shift+f2'}])
        self.assertEqual(stable['profiles']['defaults'], TERMINAL_DEFAULTS)
        self.assertEqual(self.settings(preview.read_text(encoding='utf-8'))['actions'][0]['keys'], 'ctrl+shift+f2')
        self.assertEqual(len(list(self.root.glob('*.bak'))), 2)

    def test_one_malformed_installation_does_not_block_the_others(self):
        broken = self.root / 'broken.json'
        broken.write_text('{broken}', encoding='utf-8')
        self.path.write_text('{}', encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'), *SHELL,
                                 '--settings', str(broken), '--settings', str(self.path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'Terminal setup failed: {broken}:', result.stderr)
        self.assertEqual(broken.read_text(encoding='utf-8'), '{broken}')
        self.assertEqual(self.settings(self.path.read_text(encoding='utf-8'))['actions'][0]['id'], terminal.ACTION_ID)

    def test_null_or_invalid_action_arrays(self):
        for personal, array in (('{"actions":null}', 'actions'), ('{"keybindings": null}', 'keybindings')):
            with self.subTest(personal=personal):
                updated = terminal.updated_settings(personal, LAUNCHER)
                self.assertEqual(terminal.updated_settings(updated, LAUNCHER), updated)
                result = self.settings(updated)
                self.assertEqual(result[array][0]['id'], terminal.ACTION_ID)
                self.assertEqual(result['actions'][0]['command']['commandline'], LAUNCHER)
        # Other settings still apply when the action cannot be added.
        for personal in ('{"keybindings":{}}', '{"actions":"x"}',
                         json.dumps({'actions': [{'id': terminal.ACTION_ID}] * 2})):
            with self.subTest(personal=personal):
                skipped = []
                result = self.settings(terminal.updated_settings(personal, LAUNCHER, None, skipped))
                self.assertEqual(len(skipped), 1)
                self.assertEqual(result['profiles']['defaults'], TERMINAL_DEFAULTS)
                self.assertEqual({key: value for key, value in result.items() if key != 'profiles'},
                                 json.loads(personal))
                self.path.write_text(personal, encoding='utf-8')
                terminal.configure(self.path, LAUNCHER)
                self.assertEqual(self.settings(self.path.read_text(encoding='utf-8'))['profiles']['defaults'],
                                 TERMINAL_DEFAULTS)

    def test_cli_requires_shell_except_to_uninstall(self):
        self.path.write_text('{}', encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'),
                                 '--settings', str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--shell is required', result.stderr)
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{}')

    def test_cli_uses_explicit_settings_path_and_native_commandline_quoting(self):
        self.path.write_text('{}', encoding='utf-8')
        shell = "C:\\PowerShell's unicode \u00e9\\pwsh.exe"
        result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'),
                                 '--shell', shell, '--settings', str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ctrl+Shift+F2 opens the SSH picker (dssh) in a new tab.', result.stdout)
        command = self.settings(self.path.read_text(encoding='utf-8'))['actions'][0]['command']
        self.assertEqual(command['commandline'], subprocess.list2cmdline([
            shell, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'bin/ssh-tab.ps1')]))
        self.assertEqual(command['startingDirectory'], '%USERPROFILE%')

    def test_malformed_or_ambiguous_settings_remain_untouched(self):
        for personal in ('{broken}', '[]', '{"actions":[],"actions":[]}'):
            with self.subTest(personal=personal):
                self.path.write_text(personal, encoding='utf-8')
                with self.assertRaises(ValueError):
                    terminal.configure(self.path, LAUNCHER)
                self.assertEqual(self.path.read_text(encoding='utf-8'), personal)
                self.assertFalse(list(self.root.glob('*.bak')))

    def test_backup_preserves_bytes_bom_crlf_and_reruns_do_not_write(self):
        original = b'\xef\xbb\xbf{\r\n  // personal\r\n  "theme": "dark",\r\n}\r\n'
        self.path.write_bytes(original)
        terminal.configure(self.path, LAUNCHER)
        backups = list(self.root.glob('*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        installed = self.path.read_bytes()
        self.assertTrue(installed.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n', installed.replace(b'\r\n', b''))
        with patch.object(Path, 'write_bytes') as write:
            terminal.configure(self.path, LAUNCHER)
        write.assert_not_called()

    def pwsh_profiles(self, text):
        return [entry for entry in self.settings(text)['profiles']['list']
                if entry.get('guid') in (terminal.PWSH_GUID, terminal.ADMIN_GUID)]

    def test_powershell_7_profiles_are_added_once_with_cleartype(self):
        pwsh = '"C:\\Program Files\\PowerShell\\7\\pwsh.exe"'
        for personal in ('{}', '{"profiles":{"defaults":{}}}', '{"profiles":{"list":[]}}',
                         '{"profiles":{"list":[ // only a comment\n]}}',
                         '{"profiles":{"list":[{"guid":"{a}","name":"Mine"}, // keep\n],},}',
                         '{\r\n  "profiles": {\r\n    "defaults": {}\r\n  }\r\n}\r\n'):
            with self.subTest(personal=personal):
                installed = terminal.updated_settings(personal, LAUNCHER, pwsh)
                self.assertEqual(terminal.updated_settings(installed, LAUNCHER, pwsh), installed)
                if '\r\n' in personal:
                    self.assertNotIn('\n', installed.replace('\r\n', ''))
                stub, admin = self.pwsh_profiles(installed)
                self.assertEqual(stub, {'guid': terminal.PWSH_GUID, 'antialiasingMode': 'cleartype',
                                        'source': 'Windows.Terminal.PowershellCore'})
                self.assertEqual((admin['name'], admin['commandline'], admin['elevate'],
                                  admin['startingDirectory'], admin['antialiasingMode']),
                                 (terminal.ADMIN_NAME, pwsh, True, '%USERPROFILE%', 'cleartype'))
        self.assertNotIn('list', self.settings(terminal.updated_settings('{}', LAUNCHER))['profiles'])

    def test_powershell_7_profiles_keep_user_edits_and_gist_profiles(self):
        generated = {'guid': terminal.PWSH_GUID.upper(), 'name': 'PowerShell', 'hidden': False,
                     'source': 'Windows.Terminal.PowershellCore'}
        gist = {'guid': '{0e0b8d1a-0000-4000-8000-000000000000}', 'name': 'windows powershell 7 (admin)',
                'commandline': 'pwsh.exe', 'elevate': True}
        personal = json.dumps({'profiles': {'list': [generated, gist]}}, indent=4)
        installed = terminal.updated_settings(personal, LAUNCHER, 'pwsh.exe')
        entries = self.settings(installed)['profiles']['list']
        self.assertEqual(entries, [dict(generated, antialiasingMode='cleartype'), gist])
        self.assertEqual(terminal.updated_settings(installed, LAUNCHER, 'pwsh.exe'), installed)
        edited = {'guid': terminal.PWSH_GUID, 'antialiasingMode': 'grayscale'}
        mine = {'guid': terminal.ADMIN_GUID, 'name': 'Mine', 'commandline': 'old.exe'}
        personal = terminal.updated_settings(json.dumps({'profiles': {'list': [edited, mine]}}), LAUNCHER)
        self.assertEqual(terminal.updated_settings(personal, LAUNCHER, 'pwsh.exe'), personal)
        personal = json.dumps({'profiles': {'defaults': {'antialiasingMode': 'aliased'},
                                            'list': [{'name': ''}, generated]}})
        entries = self.settings(terminal.updated_settings(personal, LAUNCHER, 'pwsh.exe'))['profiles']['list']
        self.assertEqual(entries[:2], [{'name': ''}, generated])
        self.assertEqual([entry.get('antialiasingMode') for entry in entries], [None, None, None])

    def test_powershell_7_profiles_skip_legacy_and_reject_invalid_lists(self):
        self.assertEqual(self.settings(terminal.updated_settings(
            '{"profiles":[]}', LAUNCHER, 'pwsh.exe'))['profiles'], [])
        personal = '{"profiles":{"list":{}}}'
        self.path.write_text(personal, encoding='utf-8')
        with self.assertRaises(ValueError):
            terminal.configure(self.path, LAUNCHER, 'pwsh.exe')
        self.assertEqual(self.path.read_text(encoding='utf-8'), personal)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_cli_adds_powershell_7_profiles_only_when_given(self):
        pwsh = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe'
        for arguments, expected in (([], 0), (['--pwsh', pwsh], 2)):
            with self.subTest(arguments=arguments):
                self.path.write_text('{}', encoding='utf-8')
                result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'), *SHELL,
                                         '--settings', str(self.path), *arguments],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                profiles = self.settings(self.path.read_text(encoding='utf-8'))['profiles']
                self.assertEqual(len(profiles.get('list', [])), expected)
                self.assertEqual('PowerShell 7 not found' in result.stdout, not expected)
                if expected:
                    self.assertEqual(profiles['list'][1]['commandline'], subprocess.list2cmdline([pwsh]))

    def test_discovers_all_standard_distributions_without_creating_settings(self):
        expected = [self.root / 'Packages' / f'Microsoft.WindowsTerminal{channel}_8wekyb3d8bbwe' /
                    'LocalState' / 'settings.json' for channel in ('', 'Preview', 'Canary')]
        expected.append(self.root / 'Microsoft' / 'Windows Terminal' / 'settings.json')
        self.assertEqual(terminal.settings_paths(str(self.root)), [])
        for path in expected:
            path.parent.mkdir(parents=True)
            path.write_text('{}', encoding='utf-8')
        self.assertEqual(terminal.settings_paths(str(self.root)), expected)

    def test_copied_launcher_works_outside_checkout_without_pythonpath_and_is_idempotent(self):
        checkout = self.root / "copied checkout's unicode \u00e9"
        implementation = checkout / 'dalftui/windows'
        implementation.mkdir(parents=True)
        for relative in ('bin/terminal_settings.py', 'bin/ssh-tab.ps1', 'dalftui/__init__.py',
                         'dalftui/windows/__init__.py',
                         'dalftui/windows/terminal_settings.py'):
            destination = checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        unrelated = self.root / 'unrelated working directory'
        unrelated.mkdir()
        self.path.write_text(json.dumps({'actions': LEGACY_ACTIONS, 'keybindings': LEGACY_KEYBINDINGS}), encoding='utf-8')
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        shell = "C:\\PowerShell's unicode \u00e9\\pwsh.exe"
        command = [sys.executable, str(checkout / 'bin/terminal_settings.py'), '--shell', shell,
                   '--settings', str(self.path)]

        result = subprocess.run(command, cwd=unrelated, env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.path.read_bytes()
        backups = list(self.root.glob('settings.json.dalftui-*.bak'))
        self.assertEqual(len(backups), 1)
        result = self.settings(installed.decode())
        # The copied checkout's action replaces the earlier one; the F3 action is removed.
        self.assertEqual([action['id'] for action in result['actions']], [terminal.ACTION_ID])
        self.assertEqual(result['keybindings'], [LEGACY_KEYBINDINGS[0]])
        # Windows temp paths may use an 8.3 alias; the launcher resolves it.
        self.assertEqual(result['actions'][0]['command']['commandline'], subprocess.list2cmdline([
            shell, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(checkout.resolve() / 'bin/ssh-tab.ps1')]))
        self.assertEqual(result['profiles']['defaults']['font']['face'], terminal.WINDOWS_FONT)

        result = subprocess.run(command, cwd=unrelated, env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.path.read_bytes(), installed)
        self.assertEqual(list(self.root.glob('settings.json.dalftui-*.bak')), backups)
        self.assertFalse(list(checkout.rglob('__pycache__')))

    def test_vscode_terminal_font_is_added_once_and_keeps_comments_bom_and_crlf(self):
        original = (b'\xef\xbb\xbf{\r\n    // personal\r\n    "editor.fontSize": 13, // mine\r\n'
                    b'    "files.eol": "\\n",\r\n}\r\n')
        self.path.write_bytes(original)
        terminal.configure_vscode(self.path)
        backups = list(self.root.glob('*.bak'))
        self.assertEqual([backup.read_bytes() for backup in backups], [original])
        installed = self.path.read_bytes()
        self.assertTrue(installed.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n', installed.replace(b'\r\n', b''))
        text = installed.decode('utf-8-sig')
        self.assertIn('// personal', text)
        self.assertIn('// mine', text)
        self.assertEqual(self.settings(text), {'editor.fontSize': 13, 'files.eol': '\n',
                                               **terminal.WINDOWS_VSCODE_SETTINGS})
        with patch.object(Path, 'write_bytes') as write:
            terminal.configure_vscode(self.path)
        write.assert_not_called()
        self.assertEqual(list(self.root.glob('*.bak')), backups)

    def test_vscode_font_chosen_by_user_is_replaced(self):
        personal = ('{"terminal.integrated.fontFamily": "Consolas", // mine\n'
                    ' "terminal.integrated.fontSize": 14}')
        updated = terminal.vscode_settings(personal, terminal.WINDOWS_VSCODE_SETTINGS)
        self.assertEqual(updated, '{"terminal.integrated.fontFamily": "FiraCode Nerd Font Mono", // mine\n'
                                  ' "terminal.integrated.fontSize": 12}')
        self.assertEqual(terminal.vscode_settings(updated, terminal.WINDOWS_VSCODE_SETTINGS), updated)
        # ./install on Linux desktops and macOS keeps Hack Nerd Font.
        self.assertEqual(self.settings(terminal.vscode_settings(updated))['terminal.integrated.fontFamily'],
                         'Hack Nerd Font')

    def test_vscode_earlier_windows_font_is_migrated(self):
        self.path.write_text('{"terminal.integrated.fontFamily": "Hack Nerd Font",'
                             ' "terminal.integrated.fontSize": 12}', encoding='utf-8')
        terminal.configure_vscode(self.path)
        self.assertEqual(self.settings(self.path.read_text(encoding='utf-8')), terminal.WINDOWS_VSCODE_SETTINGS)
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)

    def test_vscode_duplicate_keys_replace_the_effective_value_only(self):
        personal = ('{"terminal.integrated.fontSize": 10, "terminal.integrated.fontSize": 11,\n'
                    ' "[python]": {"terminal.integrated.fontSize": 9, "editor.tabSize": 4, "editor.tabSize": 2}}')
        updated = terminal.vscode_settings(personal)
        self.assertTrue(updated.startswith('{"terminal.integrated.fontSize": 10, "terminal.integrated.fontSize": 12,\n'
                                           ' "[python]": {"terminal.integrated.fontSize": 9, '))
        self.assertEqual(self.settings(updated)['terminal.integrated.fontFamily'], 'Hack Nerd Font')
        self.assertEqual(terminal.vscode_settings(updated), updated)

    def test_vscode_empty_or_comment_only_settings(self):
        for personal in ('', '\n', '// only a comment', '/* c */\n'):
            with self.subTest(personal=personal):
                updated = terminal.vscode_settings(personal)
                if personal.strip():
                    self.assertTrue(updated.startswith(personal))
                self.assertEqual(self.settings(updated), terminal.VSCODE_SETTINGS)
                self.assertEqual(terminal.vscode_settings(updated), updated)

    def test_vscode_malformed_settings_remain_untouched(self):
        for personal in ('{broken}', '[]'):
            with self.subTest(personal=personal):
                self.path.write_text(personal, encoding='utf-8')
                with self.assertRaises(ValueError):
                    terminal.configure_vscode(self.path)
                self.assertEqual(self.path.read_text(encoding='utf-8'), personal)
                self.assertFalse(list(self.root.glob('*.bak')))

    def test_cli_creates_vscode_settings_without_terminal_settings(self):
        missing = self.root / 'Code/User/settings.json'
        command = [sys.executable, str(ROOT / 'bin/terminal_settings.py'), *SHELL, '--vscode-settings', str(missing)]
        environment = {**os.environ, 'LOCALAPPDATA': str(self.root / 'no terminal')}
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('VS Code settings created', result.stdout)
        self.assertEqual(self.settings(missing.read_text(encoding='utf-8')), terminal.WINDOWS_VSCODE_SETTINGS)
        self.assertFalse(list(missing.parent.glob('*.bak')))
        missing.write_text('{broken}', encoding='utf-8')
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('VS Code font setup failed', result.stderr)
        self.assertIn('Windows Terminal settings not found', result.stdout)

    def test_uninstall_removes_only_setup_entries_and_keeps_comments(self):
        personal = '''{
    // Keep my defaults and shortcuts.
    "defaultProfile": "wsl-guid",
    "profiles": {"defaults": {"font": {"face": "Cascadia Code", "size": 11}}, "list": [
        {"guid": "wsl-guid", "name": "Ubuntu"} // mine
    ]},
    "actions": [
        {"command": "copy", "keys": "ctrl+shift+c"}, // my binding
    ], /* leave this here */
}'''
        installed = terminal.updated_settings(personal, LAUNCHER, 'pwsh.exe')
        removed = terminal.removed_settings(installed)
        for line in ('// Keep my defaults and shortcuts.', '// my binding', '/* leave this here */', '// mine'):
            self.assertIn(line, removed)
        self.assertNotIn('Dalftui', removed)
        result = self.settings(removed)
        self.assertEqual(result['actions'], [{'command': 'copy', 'keys': 'ctrl+shift+c'}])
        self.assertEqual(result['profiles']['list'], [{'guid': 'wsl-guid', 'name': 'Ubuntu'}])
        self.assertEqual(result['profiles']['defaults'], {'font': {'size': 11}})
        self.assertEqual(terminal.removed_settings(removed), removed)

    def test_uninstall_keeps_values_changed_after_setup(self):
        installed = terminal.updated_settings('{"keybindings": []}', LAUNCHER, 'pwsh.exe')
        settings = self.settings(installed)
        settings['actions'], settings['keybindings'] = LEGACY_ACTIONS, [dict(LEGACY_KEYBINDINGS[0])]
        stub, admin = settings['profiles']['list']
        stub['hidden'] = False
        admin['name'] = 'Renamed admin'
        settings['profiles']['defaults'] = {'font': {'face': 'Consolas'}}
        settings['keybindings'][0]['keys'] = 'ctrl+alt+s'  # Rebound in Terminal's UI.
        settings['profiles']['list'].append({'guid': '{gist-guid}', 'name': terminal.ADMIN_NAME})
        result = self.settings(terminal.removed_settings(json.dumps(settings, indent=4)))
        self.assertEqual(result['actions'], [])
        self.assertEqual(result['keybindings'], [])
        self.assertEqual(result['profiles']['defaults'], {'font': {'face': 'Consolas'}})
        self.assertEqual(result['profiles']['list'], [
            {'guid': terminal.PWSH_GUID, 'source': 'Windows.Terminal.PowershellCore', 'hidden': False},
            {'guid': '{gist-guid}', 'name': terminal.ADMIN_NAME}])
        grayscale = {'profiles': {'list': [{'guid': terminal.PWSH_GUID.upper(), 'source': 'x',
                                            'antialiasingMode': 'grayscale'}]}}
        text = json.dumps(grayscale)
        self.assertEqual(terminal.removed_settings(text), text)

    def test_uninstall_cli_backs_up_keeps_bom_crlf_and_supports_dry_run(self):
        original = b'\xef\xbb\xbf{\r\n  // personal\r\n  "theme": "dark",\r\n}\r\n'
        self.path.write_bytes(original)
        terminal.configure(self.path, LAUNCHER, 'pwsh.exe')
        vscode = self.root / 'vscode.json'
        vscode.write_bytes(b'\xef\xbb\xbf{\r\n  "editor.fontSize": 14, // mine\r\n}\r\n')
        terminal.configure_vscode(vscode)
        for backup in self.root.glob('*.bak'):
            backup.unlink()
        command = [sys.executable, str(ROOT / 'bin/terminal_settings.py'), '--uninstall',
                   '--settings', str(self.path), '--vscode-settings', str(vscode)]
        installed = self.path.read_bytes(), vscode.read_bytes()
        result = subprocess.run([*command, '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Back up and remove dalftui Terminal settings', result.stdout)
        self.assertEqual((self.path.read_bytes(), vscode.read_bytes()), installed)
        self.assertFalse(list(self.root.glob('*.bak')))
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('settings.json.dalftui-*.bak', result.stdout)
        self.assertEqual(sorted(path.read_bytes() for path in self.root.glob('*.bak')), sorted(installed))
        for path, comment in ((self.path, b'// personal'), (vscode, b'// mine')):
            content = path.read_bytes()
            self.assertTrue(content.startswith(b'\xef\xbb\xbf{\r\n'))
            self.assertNotIn(b'\n', content.replace(b'\r\n', b''))
            self.assertIn(comment, content)
            self.assertNotIn(terminal.WINDOWS_FONT.encode(), content)
            self.assertNotIn(b'cursorShape', content)
            self.assertNotIn(b'Dalftui', content)
        self.assertEqual(self.settings(vscode.read_text(encoding='utf-8-sig')), {'editor.fontSize': 14})
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No dalftui Terminal settings', result.stdout)
        self.assertIn('No dalftui VS Code settings', result.stdout)
        self.assertEqual(len(list(self.root.glob('*.bak'))), 2)

    def test_uninstall_vscode_removes_only_effective_dalftui_values(self):
        text = '{\n  "terminal.integrated.fontSize": 11,\n  "terminal.integrated.fontSize": 12,\n' \
               '  "terminal.integrated.fontFamily": "Consolas"\n}'
        self.assertEqual(self.settings(terminal.removed_vscode_settings(text)),
                         {'terminal.integrated.fontSize': 11, 'terminal.integrated.fontFamily': 'Consolas'})
        for unchanged in ('', '// only a comment\n', '{"terminal.integrated.fontSize": 12, "terminal.integrated.fontSize": 13}'):
            self.assertEqual(terminal.removed_vscode_settings(unchanged), unchanged)
        with self.assertRaises(ValueError):
            terminal.removed_vscode_settings('{broken')

    def test_uninstall_vscode_font_values_depend_on_the_platform(self):
        values = terminal.WINDOWS_VSCODE_VALUES
        for font, kept_linux, kept_windows in (('FiraCode Nerd Font Mono', True, False),
                                               ('Hack Nerd Font', False, False), ('Consolas', True, True)):
            with self.subTest(font=font):
                text = json.dumps({'terminal.integrated.fontFamily': font})
                # Windows also removes the font that earlier Windows versions set.
                self.assertEqual('fontFamily' in terminal.removed_vscode_settings(text), kept_linux)
                self.assertEqual('fontFamily' in terminal.removed_vscode_settings(text, values), kept_windows)

    def test_uninstall_removes_profile_defaults_only_while_they_are_dalftui_values(self):
        installed = self.settings(terminal.updated_settings('{"profiles": {"defaults": {"opacity": 90}}}', LAUNCHER))
        defaults = installed['profiles']['defaults']
        self.assertEqual(self.settings(terminal.removed_settings(json.dumps(installed)))['profiles']['defaults'],
                         {'opacity': 90, 'font': {}})
        defaults.update(cursorShape='vintage', padding='0', bellStyle='all')
        defaults['font']['face'] = 'Hack Nerd Font'  # Set by earlier Windows versions.
        removed = self.settings(terminal.removed_settings(json.dumps(installed)))['profiles']['defaults']
        self.assertEqual(removed, {'opacity': 90, 'font': {}, 'cursorShape': 'vintage', 'padding': '0',
                                   'bellStyle': 'all'})

    def test_uninstall_restores_defaults_that_setup_replaced(self):
        record = {}
        personal = ('{"profiles": {"defaults": {"font": {"face": "Cascadia Code", "size": 11},'
                    ' "cursorShape": "filledBox", "padding": "0", "opacity": 90}}}')
        settings = self.settings(terminal.default_settings(personal, record))
        settings['profiles']['defaults']['padding'] = '4'  # Changed after setup: kept.
        removed = self.settings(terminal.removed_settings(json.dumps(settings), record))['profiles']['defaults']
        self.assertEqual(removed, {'font': {'face': 'Cascadia Code', 'size': 11}, 'cursorShape': 'filledBox',
                                   'padding': '4', 'opacity': 90})

    def test_rerun_and_uninstall_use_the_record_next_to_the_settings(self):
        self.path.write_text('{"profiles": {"defaults": {"cursorShape": "filledBox"}}}', encoding='utf-8')
        record = self.root / ('settings.json' + terminal.RECORD_SUFFIX)
        terminal.configure(self.path, LAUNCHER)
        self.assertEqual(json.loads(record.read_text(encoding='utf-8'))['keys']['cursorShape'],
                         {'written': 'bar', 'previous': 'filledBox', 'revision': 1})
        settings = self.settings(self.path.read_text(encoding='utf-8'))
        settings['profiles']['defaults']['bellStyle'] = 'audible'
        self.path.write_text(json.dumps(settings), encoding='utf-8')
        terminal.configure(self.path, LAUNCHER)
        self.assertEqual(self.settings(self.path.read_text(encoding='utf-8'))['profiles']['defaults']['bellStyle'],
                         'audible')
        command = [sys.executable, str(ROOT / 'bin/terminal_settings.py'), '--uninstall', '--settings', str(self.path)]
        result = subprocess.run([*command, '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(record.exists())
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.settings(self.path.read_text(encoding='utf-8'))['profiles']['defaults'],
                         {'cursorShape': 'filledBox', 'bellStyle': 'audible', 'font': {}})
        self.assertFalse(record.exists())
        # Settings configured before the record existed: the values are dalftui's from now on.
        # Only the record changes, and it is still written.
        self.path.write_text(terminal.updated_settings('{}', LAUNCHER), encoding='utf-8')
        terminal.configure(self.path, LAUNCHER)
        installed = {'version': 2, 'keys': {'.'.join(key): {'written': value, 'revision': revision}
                                            for key, (value, revision) in terminal.DEFAULT_VALUES.items()}}
        self.assertEqual(json.loads(record.read_text(encoding='utf-8')), installed)
        for broken in ('{broken', '{"version": 3, "keys": {}}', '{"version": 2, "keys": {"padding": {}}}',
                       '{"applied": "padding"}'):
            with self.subTest(broken=broken):
                record.write_text(broken, encoding='utf-8')
                with patch('sys.stderr', new_callable=io.StringIO) as stderr:
                    terminal.configure(self.path, LAUNCHER)
                self.assertIn(f'Ignoring an unreadable {record.name}', stderr.getvalue())
                self.assertEqual(json.loads(record.read_text(encoding='utf-8')), installed)

    def test_settings_are_kept_unchanged_when_the_record_cannot_be_written(self):
        record = self.root / ('settings.json' + terminal.RECORD_SUFFIX)
        self.path.write_text('{"profiles": {"defaults": {"cursorShape": "filledBox"}}}', encoding='utf-8')
        terminal.configure(self.path, LAUNCHER)
        recorded = record.read_bytes()
        settings = self.settings(self.path.read_text(encoding='utf-8'))
        settings['profiles']['defaults'].update(padding='0')
        del settings['profiles']['defaults']['bellStyle']
        original = json.dumps(settings).encode()
        self.path.write_bytes(original)
        with patch.object(terminal.os, 'replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                terminal.configure(self.path, LAUNCHER)
        # The next run starts again from the same settings and record.
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(record.read_bytes(), recorded)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_record_saved_with_a_byte_order_mark_is_read(self):
        record = {'version': 2, 'keys': {'cursorShape': {'written': 'bar', 'previous': 'filledBox', 'revision': 1}}}
        terminal.record_path(self.path).write_bytes(b'\xef\xbb\xbf' + json.dumps(record).encode())
        self.assertEqual(terminal.read_record(self.path), record)

    def test_uninstall_keeps_replaced_gist_profiles_removed(self):
        installed = terminal.updated_settings(self.gist_settings('Windows PowerShell 7'), LAUNCHER, 'pwsh.exe')
        result = self.settings(terminal.removed_settings(installed))
        self.assertEqual(result['profiles']['list'], [])
        self.assertEqual(result['defaultProfile'], terminal.PWSH_GUID)

    def test_uninstall_cli_reports_malformed_settings_without_writing(self):
        self.path.write_text('{"actions": [}', encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'), '--uninstall',
                                 '--settings', str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Terminal settings were not changed', result.stderr)
        self.assertEqual(self.path.read_text(encoding='utf-8'), '{"actions": [}')
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_uninstall_cli_reports_missing_terminal_settings(self):
        result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'), '--uninstall'],
                                capture_output=True, text=True, env={**os.environ, 'LOCALAPPDATA': str(self.root)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Windows Terminal settings not found', result.stdout)

if __name__ == '__main__':
    unittest.main()
