"""mise activation in the interactive shell loaders, with a fake mise."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
# The fake activation defines the hook function mise uses and counts each run.
FAKE_MISE = ('#!/bin/sh\n'
             'echo x >> "$TEST_ACTIVATIONS"\n'
             'echo "_mise_hook() { :; }; export MISE_SHELL=$2"\n')


class MiseActivationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-shell-')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.home = self.directory / 'home'
        self.home.mkdir()
        self.activations = self.directory / 'activations'
        self.commands = self.directory / 'commands'
        self.commands.mkdir()

    def fake_mise(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        fake = directory / 'mise'
        fake.write_text(FAKE_MISE)
        fake.chmod(0o755)

    def run_shell(self, shell, rc_lines, rc_name):
        rc = self.directory / rc_name
        rc.write_text('\n'.join(rc_lines) + '\n')
        env = {key: value for key, value in os.environ.items() if not key.startswith(('MISE_', '__MISE', 'TMUX'))}
        # Leave out a real mise and oh-my-posh, so only the fakes can answer.
        path = [str(self.commands)] + [part for part in os.environ['PATH'].split(os.pathsep)
                                       if not (Path(part) / 'mise').exists() and not (Path(part) / 'oh-my-posh').exists()]
        env.update(HOME=str(self.home), PATH=os.pathsep.join(path), TEST_ACTIVATIONS=str(self.activations),
                   ZDOTDIR=str(self.directory))
        command = ([shell, '--noprofile', '--rcfile', str(rc), '-i', '-c', 'echo "$MISE_SHELL"'] if shell == 'bash'
                   else [shell, '-i', '-c', 'echo "$MISE_SHELL"'])
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        count = len(self.activations.read_text().splitlines()) if self.activations.exists() else 0
        return result.stdout.strip(), count, result.stderr

    def test_bash_activates_mise_from_local_bin_once(self):
        self.fake_mise(self.home / '.local/bin')
        source = f'. {ROOT}/config/prompt.bash'
        self.assertEqual(self.run_shell('bash', [source], 'rc')[:2], ('bash', 1))
        self.activations.unlink()
        # An activation already in ~/.bashrc is kept, and dalftui adds none.
        own = f'eval "$({self.home}/.local/bin/mise activate bash)"'
        self.assertEqual(self.run_shell('bash', [own, source], 'rc')[:2], ('bash', 1))

    def test_bash_without_mise_stays_quiet(self):
        output, count, errors = self.run_shell('bash', [f'. {ROOT}/config/prompt.bash'], 'rc')
        self.assertEqual((output, count), ('', 0))
        self.assertNotIn('mise', errors)

    @unittest.skipUnless(shutil.which('zsh'), 'zsh is required')
    def test_zsh_activates_mise_once(self):
        self.fake_mise(self.commands)
        source = f'. {ROOT}/config/prompt.zsh'
        self.assertEqual(self.run_shell('zsh', [source], '.zshrc')[:2], ('zsh', 1))
        self.activations.unlink()
        own = 'eval "$(mise activate zsh)"'
        self.assertEqual(self.run_shell('zsh', [own, source], '.zshrc')[:2], ('zsh', 1))


if __name__ == '__main__':
    unittest.main()
