"""The desktop kitty loader adds the AZERTY tab keys only on an AZERTY keyboard."""
import importlib.util
from importlib.machinery import SourceFileLoader
import io
from contextlib import redirect_stdout
import os
import subprocess
import unittest
from unittest.mock import patch

import test_install as install_tests
from test_install import ROOT, setup

GNOME = ('gsettings', 'get', 'org.gnome.desktop.input-sources', 'sources')


class KeyboardTests(install_tests.DisposableSetup):
    real_command_output = staticmethod(setup.command_output)

    def setUp(self):
        super().setUp()
        for name in ('XKB_DEFAULT_LAYOUT', 'XKB_DEFAULT_VARIANT'):
            os.environ.pop(name, None)  # setUp restores the environment.
        self.outputs = {}
        for target, value in (('command_output', lambda *command: self.outputs.get(command, '')),
                              ('SYSTEM_KEYBOARD', self.directory / 'keyboard')):
            patcher = patch.object(setup, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def layout(self):
        return setup.keyboard_layout(self.paths)

    def azerty(self, choice='auto'):
        output = io.StringIO()
        with redirect_stdout(output):
            return setup.azerty_keyboard(choice, self.paths), output.getvalue()

    def kitty_lines(self):
        return self.paths.kitty.read_text().splitlines()[1:]

    def test_sources_are_tried_in_order_and_the_first_layout_wins(self):
        self.assertIsNone(self.layout())
        (self.directory / 'keyboard').write_text('XKBMODEL="pc105"\nXKBLAYOUT="fr,us"\nXKBVARIANT="latin9,"\n')
        self.assertEqual(self.layout(), ('fr', 'latin9', str(self.directory / 'keyboard')))
        self.outputs[('localectl', 'status')] = '   X11 Layout: (unset)\n'
        self.assertEqual(self.layout(), ('fr', 'latin9', str(self.directory / 'keyboard')))
        self.outputs[('localectl', 'status')] = '   X11 Layout: us\n    X11 Model: pc105\n'
        self.assertEqual(self.layout(), ('us', '', 'localectl'))
        self.outputs[GNOME] = '@a(ss) []\n'  # GNOME's default, outside GNOME too.
        self.assertEqual(self.layout(), ('us', '', 'localectl'))
        self.outputs[GNOME] = "[('xkb', 'fr+bepo'), ('xkb', 'us')]\n"
        self.assertEqual(self.layout(), ('fr', 'bepo', 'GNOME input sources'))
        kxkbrc = self.paths.config_dir / 'kxkbrc'
        kxkbrc.parent.mkdir(parents=True)
        kxkbrc.write_text('[Layout]\nLayoutList=fr,us\nVariantList=oss,\n')
        self.assertEqual(self.layout(), ('fr', 'bepo', 'GNOME input sources'))  # Not in use.
        kxkbrc.write_text('[$Version]\nupdate_info=kxkb.upd\n\n[Layout]\nLayoutList=fr,us\nUse=true\nVariantList=oss,\n')
        self.assertEqual(self.layout(), ('fr', 'oss', 'kxkbrc'))
        os.environ.update(XKB_DEFAULT_LAYOUT='be', XKB_DEFAULT_VARIANT='')
        self.assertEqual(self.layout(), ('be', '', 'XKB_DEFAULT_LAYOUT'))

    def test_only_french_azerty_variants_get_the_keys(self):
        self.assertEqual(self.azerty(), (False, 'Keyboard: other (no layout found)\n'))
        for layout, variant, expected in (('fr', '', True), ('fr', 'oss', True), ('fr', 'latin9_nodeadkeys', True),
                                          ('fr', 'bepo', False), ('fr', 'ergol', False), ('fr', 'mac', False),
                                          ('be', '', False), ('us', '', False)):
            os.environ.update(XKB_DEFAULT_LAYOUT=layout, XKB_DEFAULT_VARIANT=variant)
            self.assertEqual(self.azerty()[0], expected, (layout, variant))
        os.environ.update(XKB_DEFAULT_LAYOUT='fr', XKB_DEFAULT_VARIANT='oss')
        self.assertEqual(self.azerty(), (True, 'Keyboard: azerty (fr+oss from XKB_DEFAULT_LAYOUT)\n'))
        self.assertEqual(self.azerty('other'), (False, 'Keyboard: other (--keyboard)\n'))
        os.environ['XKB_DEFAULT_LAYOUT'] = 'us'
        self.assertEqual(self.azerty('azerty'), (True, 'Keyboard: azerty (--keyboard)\n'))

    def test_missing_failing_or_slow_tools_give_no_output(self):
        for error in (FileNotFoundError('localectl'), subprocess.TimeoutExpired('localectl', 3), OSError('denied')):
            with patch.object(setup.subprocess, 'run', side_effect=error):
                self.assertEqual(self.real_command_output('localectl', 'status'), '')
        failed = subprocess.CompletedProcess([], 1, stdout='X11 Layout: fr\n')
        with patch.object(setup.subprocess, 'run', return_value=failed) as run:
            self.assertEqual(self.real_command_output('localectl', 'status'), '')
        self.assertLessEqual(run.call_args.kwargs['timeout'], 3)

    def test_loader_switches_between_both_variants_and_uninstalls_either(self):
        include = f'include {self.paths.root}/config/kitty.conf'
        azerty = f'include {self.paths.root}/config/kitty-azerty.conf'
        self.assertIn('map ctrl+alt+ç goto_tab 99', (self.repo / 'config/kitty-azerty.conf').read_text())
        self.assertNotIn('map ctrl+alt+-', (self.repo / 'config/kitty.conf').read_text())
        self.install(azerty=True)
        self.assertEqual(self.kitty_lines(), [include, azerty, 'globinclude local.conf'])
        self.install()
        self.assertEqual(self.kitty_lines(), [include, 'globinclude local.conf'])
        for value in (True, False):
            self.install(azerty=value)
            with redirect_stdout(io.StringIO()):
                setup.uninstall(self.paths)
            self.assertFalse(self.paths.kitty.exists())

    def test_cli_detects_on_every_desktop_run_and_the_option_overrides_it(self):
        loader = SourceFileLoader('installer_keyboard', str(ROOT / 'install'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        os.environ.update(XKB_DEFAULT_LAYOUT='fr', XKB_DEFAULT_VARIANT='oss')
        azerty = f'include {self.paths.root}/config/kitty-azerty.conf'
        with patch.object(installer, 'dependencies'), patch.object(installer, 'reload_config'), \
                patch.object(setup, 'REPO', self.repo), patch.object(setup.Paths, 'current', return_value=self.paths):
            for flags, line, included in ((['--desktop'], 'Keyboard: azerty (fr+oss from XKB_DEFAULT_LAYOUT)', True),
                                          (['--keyboard', 'other'], 'Keyboard: other (--keyboard)', False),
                                          ([], 'Keyboard: azerty (fr+oss from XKB_DEFAULT_LAYOUT)', True),
                                          (['--server', '--keyboard', 'azerty'], None, None)):
                output = io.StringIO()
                with patch('sys.argv', ['install', *flags]), redirect_stdout(output):
                    self.assertEqual(installer.main(), 0)
                if line:
                    self.assertIn(line + '\n', output.getvalue())
                    self.assertEqual(azerty in self.kitty_lines(), included)
                else:
                    self.assertNotIn('Keyboard:', output.getvalue())


if __name__ == '__main__':
    unittest.main()
