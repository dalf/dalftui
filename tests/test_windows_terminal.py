"""Terminal settings tests, runnable on Linux and native Windows."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('terminal_setup', ROOT / 'windows-terminal.py')
terminal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(terminal)


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
        updated = terminal.updated_settings(personal, 'powershell.exe -File "repo path\\windows-terminal.ps1"')
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

    def test_modern_actions_and_bindings_keep_personal_entries(self):
        personal = '{"actions": [{"id":"Personal.Copy","command":"copy"}], "keybindings": [{"id":"Personal.Copy","keys":"ctrl+c"}]}'
        result = self.settings(terminal.updated_settings(personal, 'launcher'))
        self.assertEqual(result['actions'][0]['id'], 'Personal.Copy')
        self.assertEqual(result['keybindings'][0], {'id': 'Personal.Copy', 'keys': 'ctrl+c'})
        self.assertNotIn('keys', result['actions'][1])
        self.assertEqual(result['keybindings'][1], {'id': terminal.ACTION_ID, 'keys': terminal.SHORTCUT})

    def test_handles_empty_missing_arrays_and_compact_settings(self):
        for personal in ('{}', '{ /* comment */ }', '{"theme":"dark"}',
                         '{"actions":[]}', '{"actions":[{"command":"copy"}]}',
                         '{"keybindings":[]}', '{"actions":[],"keybindings":[],}',
                         '{"actions":[{"command":"copy"} // final comment\n]}'):
            with self.subTest(personal=personal):
                result = self.settings(terminal.updated_settings(personal, 'launcher'))
                self.assertEqual(result['actions'][-1]['id'], terminal.ACTION_ID)

    def test_reruns_are_idempotent_and_moved_checkout_updates_managed_action(self):
        first = terminal.updated_settings('{"actions":[],"keybindings":[]}', 'old-launcher')
        self.assertEqual(terminal.updated_settings(first, 'old-launcher'), first)
        result = self.settings(terminal.updated_settings(first, 'new-launcher'))
        self.assertEqual(len(result['actions']), 1)
        self.assertEqual(len(result['keybindings']), 1)
        self.assertEqual(result['actions'][0]['command']['commandline'], 'new-launcher')

    def test_ui_migration_and_additional_personal_shortcuts_do_not_duplicate_entries(self):
        action = self.settings(terminal.updated_settings('{}', 'launcher'))['actions'][0]
        del action['keys']
        personal = json.dumps({'actions': [action], 'keybindings': [
            {'id': terminal.ACTION_ID, 'keys': 'ctrl+shift+f2'},
            {'id': terminal.ACTION_ID, 'keys': 'ctrl+alt+s'},
        ]})
        self.assertEqual(terminal.updated_settings(personal, 'launcher'), personal)

    def test_shortcut_conflicts_preserve_settings_without_writing_or_backup(self):
        for key in ('ctrl+shift+f2', 'SHIFT+CTRL+F2', ['ctrl+v', 'ctrl+shift+f2']):
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
        result = subprocess.run([sys.executable, str(ROOT / 'windows-terminal.py'),
                                 '--shell', shell, '--settings', str(self.path)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        command = self.settings(self.path.read_text(encoding='utf-8'))['actions'][0]['command']
        self.assertEqual(command['commandline'], subprocess.list2cmdline([
            shell, '-NoLogo', '-NoProfile', '-File', str(ROOT / 'windows-terminal.ps1')]))
        self.assertEqual(command['startingDirectory'], '%USERPROFILE%')


if __name__ == '__main__':
    unittest.main()
