"""The desktop install replaces kitty's menu entry so every window shares one process."""
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_install as install_tests
from test_install import setup


class KittyLauncherTests(install_tests.DisposableSetup):
    launcher = '[Desktop Entry]\nExec=kitty --mine\n'

    def uninstall(self):
        output = io.StringIO()
        with redirect_stdout(output):
            setup.uninstall(self.paths)
        return output.getvalue()

    def test_desktop_install_runs_one_kitty_process_and_server_install_does_not(self):
        self.install(profile='server')
        self.assertFalse(self.paths.kitty_desktop.exists())
        self.install(profile='desktop')
        self.assertIn('Exec=kitty -1', self.paths.kitty_desktop.read_text().splitlines())
        self.uninstall()
        self.assertFalse(self.paths.kitty_desktop.exists())

    def test_uninstall_restores_a_personal_launcher(self):
        self.paths.kitty_desktop.parent.mkdir(parents=True)
        self.paths.kitty_desktop.write_text(self.launcher)
        self.install()
        self.assertEqual(self.paths.kitty_desktop.read_bytes(), setup.KITTY_DESKTOP)
        self.assertIn(f'Restore {self.paths.kitty_desktop} from ', self.uninstall())
        self.assertEqual(self.paths.kitty_desktop.read_text(), self.launcher)

    def test_install_replaces_an_older_launcher_and_uninstall_keeps_an_edited_one(self):
        self.install()
        edited = self.paths.kitty_desktop.read_text() + 'NoDisplay=true\n'
        self.paths.kitty_desktop.write_text(edited)
        self.install()
        self.assertEqual(self.paths.kitty_desktop.read_bytes(), setup.KITTY_DESKTOP)
        self.paths.kitty_desktop.write_text(edited)
        self.assertIn(f'Kept edited launcher: {self.paths.kitty_desktop}', self.uninstall())
        self.assertEqual(self.paths.kitty_desktop.read_text(), edited)

    def test_launcher_honors_an_absolute_xdg_data_home(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME': '/data'}):
            self.assertEqual(setup.Paths.current().kitty_desktop, Path('/data/applications/kitty.desktop'))
        with patch.dict(os.environ, {'XDG_DATA_HOME': 'relative'}):
            self.assertEqual(setup.Paths.current().kitty_desktop,
                             Path.home() / '.local/share/applications/kitty.desktop')


if __name__ == '__main__':
    unittest.main()
