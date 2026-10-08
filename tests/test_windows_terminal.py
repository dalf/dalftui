"""Terminal settings tests, runnable on Linux and native Windows."""
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

# The Ctrl+Shift+F2/F3 entries that earlier versions installed, in the modern form.
LEGACY_ACTIONS = [
    {'id': terminal.ACTION_ID, 'name': 'SSH host picker (dssh)', 'command': {
        'action': 'newTab', 'commandline': 'powershell.exe -NoLogo -NoProfile -File "C:\\dalftui\\bin/ssh-tab.ps1"',
        'startingDirectory': '%USERPROFILE%', 'tabTitle': 'SSH', 'suppressApplicationTitle': False, 'elevate': False}},
    {'id': terminal.EDITOR_ACTION_ID, 'name': 'Open current folder in VS Code',
     'command': {'action': 'sendInput', 'input': '\x02\x1bOR'}},
]
LEGACY_KEYBINDINGS = [{'id': terminal.ACTION_ID, 'keys': 'ctrl+shift+f2'},
                      {'id': terminal.EDITOR_ACTION_ID, 'keys': 'ctrl+shift+f3'}]


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
        updated = terminal.updated_settings(personal)
        for line in ('// Keep my defaults and shortcuts.', '// my binding', '/* leave this here */',
                     '"theme": "\u00e9 // not a comment"', '"url": "https://example.org/*not a comment*/"'):
            self.assertIn(line, updated)
        result = self.settings(updated)
        self.assertEqual(result['defaultProfile'], 'wsl-guid')
        self.assertEqual(result['actions'][0], {'command': 'copy', 'keys': 'ctrl+shift+c'})
        self.assertEqual(len(result['actions']), 1)
        self.assertNotIn('keybindings', result)

    def test_default_face_uses_prompt_font_once(self):
        for profiles in ('{"defaults": {"font": {"face": "Cascadia Code"}}, "list": []}',
                         '{"defaults": {"fontFace": "Consolas"}, "list": []}',
                         '{"defaults": {"font": {"size": 11}}, "list": []}',
                         '{"list": []}',
                         '{"defaults": {"font": {"face": "Hack Nerd Font"}}}'):
            with self.subTest(profiles=profiles):
                updated = terminal.updated_settings('{"profiles": ' + profiles + '}')
                self.assertEqual(self.settings(updated)['profiles']['defaults']['font']['face'], 'Hack Nerd Font')
                self.assertEqual(terminal.updated_settings(updated), updated)
        legacy = self.settings(terminal.updated_settings('{"profiles": []}'))
        self.assertEqual(legacy['profiles'], [])

    def test_rerun_removes_shortcuts_from_earlier_versions_and_keeps_personal_entries(self):
        copy = {'id': 'Personal.Copy', 'command': 'copy'}
        mine = {'id': 'Personal.Mine', 'keys': 'ctrl+shift+f2'}
        inline = [dict(action, keys=binding['keys']) for action, binding in zip(LEGACY_ACTIONS, LEGACY_KEYBINDINGS)]
        rebound = {'id': terminal.ACTION_ID, 'keys': 'ctrl+alt+s'}
        for old in ({'actions': [copy, *LEGACY_ACTIONS], 'keybindings': [*LEGACY_KEYBINDINGS, rebound, mine]},
                    {'actions': [*inline, copy, mine]}):
            with self.subTest(old=old):
                updated = terminal.updated_settings(json.dumps(old, indent=4))
                result = self.settings(updated)
                self.assertEqual(result['actions'], [copy] if 'keybindings' in old else [copy, mine])
                self.assertEqual(result.get('keybindings', [mine]), [mine])
                self.assertEqual(terminal.updated_settings(updated), updated)

    def test_does_not_add_actions_or_bindings(self):
        for personal in ('{}', '{ /* comment */ }', '{"theme":"dark"}',
                         '{"actions":[]}', '{"actions":[{"command":"copy"}]}',
                         '{"keybindings":[]}', '{"actions":[],"keybindings":[],}',
                         '{"actions":[{"command":"copy"} // final comment\n]}',
                         '{"actions":null}', '{"keybindings":{}}'):
            with self.subTest(personal=personal):
                original = self.settings(personal)
                result = self.settings(terminal.updated_settings(personal))
                for name in ('actions', 'keybindings'):
                    self.assertEqual(result.get(name), original.get(name))

    def test_malformed_or_ambiguous_settings_remain_untouched(self):
        for personal in ('{broken}', '[]', '{"actions":[],"actions":[]}'):
            with self.subTest(personal=personal):
                self.path.write_text(personal, encoding='utf-8')
                with self.assertRaises(ValueError):
                    terminal.configure(self.path)
                self.assertEqual(self.path.read_text(encoding='utf-8'), personal)
                self.assertFalse(list(self.root.glob('*.bak')))

    def test_backup_preserves_bytes_bom_crlf_and_reruns_do_not_write(self):
        original = b'\xef\xbb\xbf{\r\n  // personal\r\n  "theme": "dark",\r\n}\r\n'
        self.path.write_bytes(original)
        terminal.configure(self.path)
        backups = list(self.root.glob('*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        installed = self.path.read_bytes()
        self.assertTrue(installed.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n', installed.replace(b'\r\n', b''))
        with patch.object(Path, 'write_bytes') as write:
            terminal.configure(self.path)
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
                installed = terminal.updated_settings(personal, pwsh)
                self.assertEqual(terminal.updated_settings(installed, pwsh), installed)
                if '\r\n' in personal:
                    self.assertNotIn('\n', installed.replace('\r\n', ''))
                stub, admin = self.pwsh_profiles(installed)
                self.assertEqual(stub, {'guid': terminal.PWSH_GUID, 'antialiasingMode': 'cleartype',
                                        'source': 'Windows.Terminal.PowershellCore'})
                self.assertEqual((admin['name'], admin['commandline'], admin['elevate'],
                                  admin['startingDirectory'], admin['antialiasingMode']),
                                 (terminal.ADMIN_NAME, pwsh, True, '%USERPROFILE%', 'cleartype'))
        self.assertNotIn('list', self.settings(terminal.updated_settings('{}'))['profiles'])

    def test_powershell_7_profiles_keep_user_edits_and_gist_profiles(self):
        generated = {'guid': terminal.PWSH_GUID.upper(), 'name': 'PowerShell', 'hidden': False,
                     'source': 'Windows.Terminal.PowershellCore'}
        gist = {'guid': '{0e0b8d1a-0000-4000-8000-000000000000}', 'name': 'windows powershell 7 (admin)',
                'commandline': 'pwsh.exe', 'elevate': True}
        personal = json.dumps({'profiles': {'list': [generated, gist]}}, indent=4)
        installed = terminal.updated_settings(personal, 'pwsh.exe')
        entries = self.settings(installed)['profiles']['list']
        self.assertEqual(entries, [dict(generated, antialiasingMode='cleartype'), gist])
        self.assertEqual(terminal.updated_settings(installed, 'pwsh.exe'), installed)
        edited = {'guid': terminal.PWSH_GUID, 'antialiasingMode': 'grayscale'}
        mine = {'guid': terminal.ADMIN_GUID, 'name': 'Mine', 'commandline': 'old.exe'}
        personal = terminal.updated_settings(json.dumps({'profiles': {'list': [edited, mine]}}))
        self.assertEqual(terminal.updated_settings(personal, 'pwsh.exe'), personal)
        personal = json.dumps({'profiles': {'defaults': {'antialiasingMode': 'aliased'},
                                            'list': [{'name': ''}, generated]}})
        entries = self.settings(terminal.updated_settings(personal, 'pwsh.exe'))['profiles']['list']
        self.assertEqual(entries[:2], [{'name': ''}, generated])
        self.assertEqual([entry.get('antialiasingMode') for entry in entries], [None, None, None])

    def test_powershell_7_profiles_skip_legacy_and_reject_invalid_lists(self):
        self.assertEqual(self.settings(terminal.updated_settings(
            '{"profiles":[]}', 'pwsh.exe'))['profiles'], [])
        personal = '{"profiles":{"list":{}}}'
        self.path.write_text(personal, encoding='utf-8')
        with self.assertRaises(ValueError):
            terminal.configure(self.path, 'pwsh.exe')
        self.assertEqual(self.path.read_text(encoding='utf-8'), personal)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_cli_adds_powershell_7_profiles_only_when_given(self):
        pwsh = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe'
        for arguments, expected in (([], 0), (['--pwsh', pwsh], 2)):
            with self.subTest(arguments=arguments):
                self.path.write_text('{}', encoding='utf-8')
                result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'),
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
        for relative in ('bin/terminal_settings.py', 'dalftui/__init__.py',
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
        command = [sys.executable, str(checkout / 'bin/terminal_settings.py'), '--settings', str(self.path)]

        result = subprocess.run(command, cwd=unrelated, env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.path.read_bytes()
        backups = list(self.root.glob('settings.json.dalftui-*.bak'))
        self.assertEqual(len(backups), 1)
        result = self.settings(installed.decode())
        self.assertEqual((result['actions'], result['keybindings']), ([], []))
        self.assertEqual(result['profiles']['defaults']['font']['face'], terminal.PROMPT_FONT)

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
                                               **terminal.VSCODE_SETTINGS})
        with patch.object(Path, 'write_bytes') as write:
            terminal.configure_vscode(self.path)
        write.assert_not_called()
        self.assertEqual(list(self.root.glob('*.bak')), backups)

    def test_vscode_font_chosen_by_user_is_replaced(self):
        personal = ('{"terminal.integrated.fontFamily": "Consolas", // mine\n'
                    ' "terminal.integrated.fontSize": 14}')
        updated = terminal.vscode_settings(personal)
        self.assertEqual(updated, '{"terminal.integrated.fontFamily": "Hack Nerd Font", // mine\n'
                                  ' "terminal.integrated.fontSize": 12}')
        self.assertEqual(terminal.vscode_settings(updated), updated)

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
        command = [sys.executable, str(ROOT / 'bin/terminal_settings.py'), '--vscode-settings', str(missing)]
        environment = {**os.environ, 'LOCALAPPDATA': str(self.root / 'no terminal')}
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('VS Code settings created', result.stdout)
        self.assertEqual(self.settings(missing.read_text(encoding='utf-8')), terminal.VSCODE_SETTINGS)
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
        installed = terminal.updated_settings(personal, 'pwsh.exe')
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
        installed = terminal.updated_settings('{"keybindings": []}', 'pwsh.exe')
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
        terminal.configure(self.path, 'pwsh.exe')
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
            self.assertNotIn(b'Hack Nerd Font', content)
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
