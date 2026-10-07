"""Discover the correct prompt file from interactive login startup."""
from contextlib import redirect_stdout
import io
import shutil
import unittest
from unittest.mock import patch

import test_install as install_tests
from dalftui.linux import setup


class ZshStartupTests(install_tests.DisposableSetup):
    def setUp(self):
        super().setUp()
        platform = patch.object(setup.sys, 'platform', 'darwin')
        platform.start()
        self.addCleanup(platform.stop)

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is required')
    def test_interactive_zprofile_selects_prompt_file_for_install_and_uninstall(self):
        (self.paths.home_dir / '.zprofile').write_text(
            'print -r -- "profile banner"\n'
            'if [[ -o interactive && -o login ]]; then ZDOTDIR=$HOME/zp; fi\n')
        directory = self.paths.home_dir / 'zp'
        directory.mkdir()
        rc = directory / '.zshrc'
        original = 'typeset personal_setting=kept\n'
        rc.write_text(original)
        for name in ('.zlogin', '.zlogout'):
            (directory / name).write_text(
                'ZDOTDIR=$HOME/too-late\nprint -r -- "login or logout banner"\n'
                'print -r -- loaded >> "$HOME/later-startup"\n')
        self.assertEqual(self.paths.zshrc, rc)
        self.install(profile='macos')
        installed = rc.read_text()
        self.assertTrue(installed.startswith(original + setup.PROMPT_MARKER + '\n'))
        self.assertFalse((self.paths.home_dir / '.zshrc').exists())
        self.assertIsNone(self.install(profile='macos'))
        self.assertEqual(rc.read_text(), installed)
        with redirect_stdout(io.StringIO()):
            setup.uninstall(self.paths)
        self.assertEqual(rc.read_text(), original)
        self.assertFalse((self.paths.home_dir / 'later-startup').exists())

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is required')
    def test_zdotdir_probe_stops_before_existing_prompt_changes_directory(self):
        (self.paths.home_dir / '.zprofile').write_text(
            'if [[ -o interactive ]]; then ZDOTDIR=$HOME/zp; fi\n')
        directory = self.paths.home_dir / 'zp'
        directory.mkdir()
        rc = directory / '.zshrc'
        original = 'ZDOTDIR=$HOME/too-late\nprint -r -- loaded >> "$HOME/prompt-loaded"\n'
        rc.write_text(original)
        self.assertEqual(self.paths.zshrc, rc)
        self.install(profile='macos')
        with redirect_stdout(io.StringIO()):
            setup.uninstall(self.paths)
        self.assertEqual(rc.read_text(), original)
        self.assertFalse((self.paths.home_dir / 'prompt-loaded').exists())

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is required')
    def test_zdotdir_probe_respects_disabled_profile_startup(self):
        (self.paths.home_dir / '.zshenv').write_text('ZDOTDIR=$HOME/zd\nunsetopt rcs\n')
        directory = self.paths.home_dir / 'zd'
        directory.mkdir()
        (directory / '.zprofile').write_text('ZDOTDIR=$HOME/not-read\n')
        self.assertEqual(self.paths.zshrc, directory / '.zshrc')


if __name__ == '__main__':
    unittest.main()
