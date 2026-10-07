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
        updated = terminal.updated_settings(personal, 'powershell.exe -File "repo path\\bin/ssh-tab.ps1"')
        for line in ('// Keep my defaults and shortcuts.', '// my binding', '/* leave this here */',
                     '"theme": "\u00e9 // not a comment"', '"url": "https://example.org/*not a comment*/"'):
            self.assertIn(line, updated)
        result = self.settings(updated)
        self.assertEqual(result['defaultProfile'], 'wsl-guid')
        self.assertEqual(result['actions'][0], {'command': 'copy', 'keys': 'ctrl+shift+c'})
        action = result['actions'][1]
        self.assertEqual(action['keys'], 'ctrl+shift+f2')
        self.assertEqual(action['command']['action'], 'newTab')
        self.assertNotIn('profile', action['command'])
        self.assertFalse(action['command']['suppressApplicationTitle'])
        editor = result['actions'][2]
        self.assertEqual(editor['keys'], 'ctrl+shift+f3')
        self.assertEqual(editor['command'], {'action': 'sendInput', 'input': '\x02\x1bOR'})

    def test_default_face_uses_prompt_font_once(self):
        for profiles in ('{"defaults": {"font": {"face": "Cascadia Code"}}, "list": []}',
                         '{"defaults": {"fontFace": "Consolas"}, "list": []}',
                         '{"defaults": {"font": {"size": 11}}, "list": []}',
                         '{"list": []}',
                         '{"defaults": {"font": {"face": "Hack Nerd Font"}}}'):
            with self.subTest(profiles=profiles):
                updated = terminal.updated_settings('{"profiles": ' + profiles + '}', 'launcher')
                self.assertEqual(self.settings(updated)['profiles']['defaults']['font']['face'], 'Hack Nerd Font')
                self.assertEqual(terminal.updated_settings(updated, 'launcher'), updated)
        legacy = self.settings(terminal.updated_settings('{"profiles": []}', 'launcher'))
        self.assertEqual(legacy['profiles'], [])

    def test_modern_actions_and_bindings_keep_personal_entries(self):
        personal = '{"actions": [{"id":"Personal.Copy","command":"copy"}], "keybindings": [{"id":"Personal.Copy","keys":"ctrl+c"}]}'
        result = self.settings(terminal.updated_settings(personal, 'launcher'))
        self.assertEqual(result['actions'][0]['id'], 'Personal.Copy')
        self.assertEqual(result['keybindings'][0], {'id': 'Personal.Copy', 'keys': 'ctrl+c'})
        self.assertNotIn('keys', result['actions'][1])
        self.assertEqual(result['keybindings'][1], {'id': terminal.ACTION_ID, 'keys': terminal.SHORTCUT})
        self.assertEqual(result['keybindings'][2], {'id': terminal.EDITOR_ACTION_ID, 'keys': terminal.EDITOR_SHORTCUT})

    def test_handles_empty_missing_arrays_and_compact_settings(self):
        for personal in ('{}', '{ /* comment */ }', '{"theme":"dark"}',
                         '{"actions":[]}', '{"actions":[{"command":"copy"}]}',
                         '{"keybindings":[]}', '{"actions":[],"keybindings":[],}',
                         '{"actions":[{"command":"copy"} // final comment\n]}'):
            with self.subTest(personal=personal):
                result = self.settings(terminal.updated_settings(personal, 'launcher'))
                self.assertEqual({entry.get('id') for entry in result['actions'] if 'id' in entry},
                                 {terminal.ACTION_ID, terminal.EDITOR_ACTION_ID})

    def test_reruns_are_idempotent_and_moved_checkout_updates_managed_action(self):
        first = terminal.updated_settings('{"actions":[],"keybindings":[]}', 'old-launcher')
        self.assertEqual(terminal.updated_settings(first, 'old-launcher'), first)
        result = self.settings(terminal.updated_settings(first, 'new-launcher'))
        self.assertEqual(len(result['actions']), 2)
        self.assertEqual(len(result['keybindings']), 2)
        self.assertEqual(result['actions'][0]['command']['commandline'], 'new-launcher')

    def test_ui_migration_and_additional_personal_shortcuts_do_not_duplicate_entries(self):
        actions = self.settings(terminal.updated_settings('{}', 'launcher'))['actions']
        for action in actions:
            del action['keys']
        personal = json.dumps({'actions': actions, 'keybindings': [
            {'id': terminal.ACTION_ID, 'keys': 'ctrl+shift+f2'},
            {'id': terminal.EDITOR_ACTION_ID, 'keys': 'ctrl+shift+f3'},
            {'id': terminal.ACTION_ID, 'keys': 'ctrl+alt+s'},
        ], 'profiles': {'defaults': {'font': {'face': 'Hack Nerd Font'}}}})
        self.assertEqual(terminal.updated_settings(personal, 'launcher'), personal)

    def test_shortcut_conflicts_preserve_settings_without_writing_or_backup(self):
        for key in ('ctrl+shift+f2', 'SHIFT+CTRL+F2', ['ctrl+v', 'ctrl+shift+f2'],
                    'ctrl+shift+f3', 'SHIFT+CTRL+F3', ['ctrl+v', 'ctrl+shift+f3']):
            for array in ('actions', 'keybindings'):
                with self.subTest(key=key, array=array):
                    personal = json.dumps({array: [{'id': 'Personal.Action', 'keys': key}]})
                    self.path.write_text(personal, encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'already has a binding'):
                        terminal.configure(self.path, 'launcher')
                    self.assertEqual(self.path.read_text(encoding='utf-8'), personal)
                    self.assertFalse(list(self.root.glob('*.bak')))

    def test_malformed_or_ambiguous_settings_remain_untouched(self):
        for personal in ('{broken}', '[]', '{"actions":null}', '{"keybindings":{}}',
                         '{"actions":[],"actions":[]}',
                         json.dumps({'actions': [{'id': terminal.ACTION_ID}] * 2})):
            with self.subTest(personal=personal):
                self.path.write_text(personal, encoding='utf-8')
                with self.assertRaises(ValueError):
                    terminal.configure(self.path, 'launcher')
                self.assertEqual(self.path.read_text(encoding='utf-8'), personal)
                self.assertFalse(list(self.root.glob('*.bak')))

    def test_backup_preserves_bytes_bom_crlf_and_reruns_do_not_write(self):
        original = b'\xef\xbb\xbf{\r\n  // personal\r\n  "theme": "dark",\r\n}\r\n'
        self.path.write_bytes(original)
        terminal.configure(self.path, 'launcher')
        backups = list(self.root.glob('*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        installed = self.path.read_bytes()
        self.assertTrue(installed.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n', installed.replace(b'\r\n', b''))
        with patch.object(Path, 'write_bytes') as write:
            terminal.configure(self.path, 'launcher')
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
                installed = terminal.updated_settings(personal, 'launcher', pwsh)
                self.assertEqual(terminal.updated_settings(installed, 'launcher', pwsh), installed)
                if '\r\n' in personal:
                    self.assertNotIn('\n', installed.replace('\r\n', ''))
                stub, admin = self.pwsh_profiles(installed)
                self.assertEqual(stub, {'guid': terminal.PWSH_GUID, 'antialiasingMode': 'cleartype',
                                        'source': 'Windows.Terminal.PowershellCore'})
                self.assertEqual((admin['name'], admin['commandline'], admin['elevate'],
                                  admin['startingDirectory'], admin['antialiasingMode']),
                                 (terminal.ADMIN_NAME, pwsh, True, '%USERPROFILE%', 'cleartype'))
        self.assertNotIn('list', self.settings(terminal.updated_settings('{}', 'launcher'))['profiles'])

    def test_powershell_7_profiles_keep_user_edits_and_gist_profiles(self):
        generated = {'guid': terminal.PWSH_GUID.upper(), 'name': 'PowerShell', 'hidden': False,
                     'source': 'Windows.Terminal.PowershellCore'}
        gist = {'guid': '{0e0b8d1a-0000-4000-8000-000000000000}', 'name': 'windows powershell 7 (admin)',
                'commandline': 'pwsh.exe', 'elevate': True}
        personal = json.dumps({'profiles': {'list': [generated, gist]}}, indent=4)
        installed = terminal.updated_settings(personal, 'launcher', 'pwsh.exe')
        entries = self.settings(installed)['profiles']['list']
        self.assertEqual(entries, [dict(generated, antialiasingMode='cleartype'), gist])
        self.assertEqual(terminal.updated_settings(installed, 'launcher', 'pwsh.exe'), installed)
        edited = {'guid': terminal.PWSH_GUID, 'antialiasingMode': 'grayscale'}
        mine = {'guid': terminal.ADMIN_GUID, 'name': 'Mine', 'commandline': 'old.exe'}
        personal = terminal.updated_settings(json.dumps({'profiles': {'list': [edited, mine]}}), 'launcher')
        self.assertEqual(terminal.updated_settings(personal, 'launcher', 'pwsh.exe'), personal)
        personal = json.dumps({'profiles': {'defaults': {'antialiasingMode': 'aliased'},
                                            'list': [{'name': ''}, generated]}})
        entries = self.settings(terminal.updated_settings(personal, 'launcher', 'pwsh.exe'))['profiles']['list']
        self.assertEqual(entries[:2], [{'name': ''}, generated])
        self.assertEqual([entry.get('antialiasingMode') for entry in entries], [None, None, None])

    def test_powershell_7_profiles_skip_legacy_and_reject_invalid_lists(self):
        self.assertEqual(self.settings(terminal.updated_settings(
            '{"profiles":[]}', 'launcher', 'pwsh.exe'))['profiles'], [])
        personal = '{"profiles":{"list":{}}}'
        self.path.write_text(personal, encoding='utf-8')
        with self.assertRaises(ValueError):
            terminal.configure(self.path, 'launcher', 'pwsh.exe')
        self.assertEqual(self.path.read_text(encoding='utf-8'), personal)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_cli_adds_powershell_7_profiles_only_when_given(self):
        pwsh = 'C:\\Program Files\\PowerShell\\7\\pwsh.exe'
        for arguments, expected in (([], 0), (['--pwsh', pwsh], 2)):
            with self.subTest(arguments=arguments):
                self.path.write_text('{}', encoding='utf-8')
                result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'),
                                         '--shell', 'pwsh.exe', '--settings', str(self.path), *arguments],
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

    def test_cli_uses_explicit_settings_path_and_native_commandline_quoting(self):
        self.path.write_text('{}', encoding='utf-8')
        shell = "C:\\PowerShell's unicode \u00e9\\pwsh.exe"
        result = subprocess.run([sys.executable, str(ROOT / 'bin/terminal_settings.py'),
                                 '--shell', shell, '--settings', str(self.path)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        command = self.settings(self.path.read_text(encoding='utf-8'))['actions'][0]['command']
        self.assertEqual(command['commandline'], subprocess.list2cmdline([
            shell, '-NoLogo', '-NoProfile', '-File', str(ROOT / 'bin/ssh-tab.ps1')]))
        self.assertEqual(command['startingDirectory'], '%USERPROFILE%')

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
        self.path.write_text('{"actions":[],"keybindings":[]}', encoding='utf-8')
        shell = "C:\\PowerShell's unicode \u00e9\\pwsh.exe"
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        command = [sys.executable, str(checkout / 'bin/terminal_settings.py'),
                   '--shell', shell, '--settings', str(self.path)]

        result = subprocess.run(command, cwd=unrelated, env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.path.read_bytes()
        backups = list(self.root.glob('settings.json.dalftui-*.bak'))
        self.assertEqual(len(backups), 1)
        action = self.settings(installed.decode())['actions'][0]['command']
        # Windows temp paths may use an 8.3 alias; the launcher resolves it.
        self.assertEqual(action['commandline'], subprocess.list2cmdline([
            shell, '-NoLogo', '-NoProfile', '-File', str(checkout.resolve() / 'bin/ssh-tab.ps1')]))

        result = subprocess.run(command, cwd=unrelated, env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.path.read_bytes(), installed)
        self.assertEqual(list(self.root.glob('settings.json.dalftui-*.bak')), backups)
        self.assertFalse(list(checkout.rglob('__pycache__')))

    def test_upgrade_from_picker_only_adds_editor_without_rewriting_picker(self):
        both = self.settings(terminal.updated_settings('{"actions":[],"keybindings":[]}', 'launcher'))
        original = json.dumps({'actions': [both['actions'][0]], 'keybindings': [both['keybindings'][0]]})
        upgraded = terminal.updated_settings(original, 'launcher')
        result = self.settings(upgraded)
        self.assertEqual(result, both)
        self.assertEqual(terminal.updated_settings(upgraded, 'launcher'), upgraded)
        self.assertIn(json.dumps(both['actions'][0]), upgraded)


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
        command = [sys.executable, str(ROOT / 'bin/terminal_settings.py'), '--shell', 'pwsh',
                   '--vscode-settings', str(missing)]
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

if __name__ == '__main__':
    unittest.main()
