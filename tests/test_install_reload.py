"""./install reloads a running tmux server at the end, through a private socket."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import shutil
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
from test_install import ROOT, TmuxFixture, setup  # pylint: disable=wrong-import-position


@unittest.skipUnless(shutil.which('tmux'), 'tmux is required')
class InstallReloadTests(TmuxFixture):
    profile = 'server'

    def run_install(self, *flags):
        loader = SourceFileLoader('installer_entry', str(ROOT / 'install'))
        installer = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(installer)
        output = io.StringIO()
        with patch.object(setup.Paths, 'current', return_value=self.paths), \
                patch.object(installer, 'dependencies'), patch.object(sys, 'argv', ['install', *flags]), \
                redirect_stdout(output), redirect_stderr(output):
            status = installer.main()
        return status, output.getvalue()

    def test_install_reloads_the_running_server(self):
        self.start()  # Started without dalftui's configuration.
        status, output = self.run_install('--socket', str(self.socket))
        self.assertEqual(status, 0, output)
        self.assertIn('tmux configuration reloaded', output)
        self.assertEqual(self.tmux('show-options', '-gv', '@dalftui_profile'), 'server')

    def test_dry_run_does_not_reload(self):
        self.start()
        status, output = self.run_install('--dry-run', '--socket', str(self.socket))
        self.assertEqual(status, 0, output)
        self.assertEqual(self.tmux('show-options', '-gqv', '@dalftui_profile'), '')

    def test_a_failed_reload_fails_the_install(self):
        with patch.object(setup.shutil, 'which', return_value=None):  # No uv: reload refuses.
            status, output = self.run_install('--socket', str(self.socket))
        self.assertEqual(status, 1)
        self.assertIn('Reload failed: uv is missing', output)


if __name__ == '__main__':
    unittest.main()
