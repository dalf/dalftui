"""Run SSH startup scripts against isolated remote homes and executables."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dalftui.linux.setup as setup
from dalftui.vscode import EditorBridge

from dalftui import ssh as picker


@unittest.skipIf(sys.platform == 'win32', 'Remote startup runs in a POSIX shell')
class SshAutoTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-ssh-auto-')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.home = self.directory / 'remote home'
        self.home.mkdir()
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        # An isolated PATH ensures the real machine's tmux cannot affect tests.
        for command in ('sh', 'stat', 'id', 'mkdir', 'cat', 'rm', 'rmdir'):
            (self.bin / command).symlink_to(shutil.which(command))
        (self.bin / 'python3').symlink_to(sys.executable)
        self.log = self.directory / 'command'
        self.editor_env = self.directory / 'editor-env'
        self.tmux = self.bin / 'tmux'
        self.tmux.write_text('#!/bin/sh\n'
                             'if [ "$1" = list-sessions ]; then exit 0; fi\n'
                             'printf "%s\\n" "$@" > "$TEST_COMMAND_LOG"\n'
                             'printf "%s\\n" "${DALFTUI_EDITOR_SOCKET-unset}" '
                             '"${DALFTUI_EDITOR_TOKEN-unset}" > "$TEST_EDITOR_ENV"\n')
        self.tmux.chmod(0o755)
        self.shell = self.bin / 'login-shell'
        self.shell.write_text('#!/bin/sh\n'
                              'printf "shell\\n%s\\n" "$@" > "$TEST_COMMAND_LOG"\n'
                              'printf "%s\\n" "${DALFTUI_EDITOR_SOCKET-unset}" '
                              '"${DALFTUI_EDITOR_TOKEN-unset}" > "$TEST_EDITOR_ENV"\n'
                              'exit "${TEST_SHELL_STATUS:-0}"\n')
        self.shell.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME='',
                        PATH=str(self.bin), SHELL=str(self.shell),
                        TEST_COMMAND_LOG=str(self.log), TEST_EDITOR_ENV=str(self.editor_env),
                        DALFTUI_EDITOR_SOCKET='stale-endpoint', DALFTUI_EDITOR_TOKEN='stale-token')
        self.real_run = subprocess.run

    def install(self, config=None, checkout=ROOT):
        paths = setup.Paths(self.home, config or self.home / '.config',
                            self.home / '.local/state')
        with redirect_stdout(io.StringIO()):
            setup.install(paths, checkout, profile='server')

    def install_test_checkout(self, protocol_version=None):
        # Use independent files: the real installation symlinks to ROOT, which
        # must never be modified to simulate an old or incompatible server.
        checkout = self.home / '.config/dalftui'
        (checkout / 'config').mkdir(parents=True)
        (checkout / 'bin').mkdir()
        (checkout / 'bin/vscode.py').touch()
        (checkout / 'config/tmux.conf').touch()
        if protocol_version is not None:
            (checkout / 'bridge_protocol.py').write_text(
                f'print({protocol_version!r})\n')

    def remote_command(self, *, rgb=False, **env):
        return self.real_run(shlex.split(picker.ssh_command('server', rgb=rgb)[-1]),
                             env=dict(self.env, **env), capture_output=True, text=True, timeout=5)

    def prepare(self):
        bridge = EditorBridge('server', transport='tcp')
        bridge.remote_directory = str(self.directory / 'credentials')
        bridge.remote_owner_file = bridge.remote_directory + '/claim.owner'
        bridge.remote_token_file = bridge.remote_directory + '/token'
        bridge.remote_socket = bridge.remote_directory + '/editor.sock'

        def local_ssh(command, **kwargs):
            self.assertNotIn('-R', command)
            return self.real_run(shlex.split(command[-1]), capture_output=True, timeout=5, **kwargs)

        with patch.object(picker.subprocess, 'run', side_effect=local_ssh):
            prepared = picker.prepare_editor_credentials('server', 'alice', bridge, self.env,
                                                          check_installation=True)
        self.assertFalse(hasattr(bridge, 'listener'))
        return prepared, bridge

    def test_missing_tmux_silently_starts_a_login_shell_and_preserves_its_status(self):
        self.tmux.rename(self.bin / 'disabled-tmux')
        for status in ('0', '23'):
            with self.subTest(status=status):
                result = self.remote_command(TEST_SHELL_STATUS=status)
                self.assertEqual(result.returncode, int(status), result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, '')
                self.assertEqual(self.log.read_text().splitlines(), ['shell', '-l'])
                self.assertEqual(self.editor_env.read_text().splitlines(), ['unset', 'unset'])

    def test_native_tmux_works_without_dalftui_or_editor_credentials(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            prepared, bridge = self.prepare()
        self.assertEqual(output.getvalue(), '')
        self.assertFalse(prepared)
        self.assertFalse(Path(bridge.remote_directory).exists())
        result = self.remote_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.log.read_text().splitlines(), ['new-session', '-A', '-s', '0'])
        self.assertEqual(self.editor_env.read_text().splitlines(), ['unset', 'unset'])

    def test_rgb_hint_reaches_new_and_attached_clients_without_changing_credentials(self):
        self.tmux.write_text('''#!/bin/sh
hint=none
if [ "$1" = -T ]; then
    [ "$2" = RGB ] || exit 2
    hint=$2
    shift 2
fi
if [ "$1" = -V ]; then exit 0; fi
if [ "$1" = list-sessions ]; then
    printf '%s' "$TEST_SESSION_ROWS"
    exit 0
fi
printf '%s\\n' "$hint" "$@" > "$TEST_COMMAND_LOG"
printf '%s\\n' "${DALFTUI_EDITOR_SOCKET-unset}" "${DALFTUI_EDITOR_TOKEN-unset}" > "$TEST_EDITOR_ENV"
''')
        for rows, expected in (('', ['new-session', '-A', '-s', '0']),
                               ('$5 0\n', ['attach-session', '-t', '$5'])):
            with self.subTest(rows=rows):
                result = self.remote_command(rgb=True, TEST_SESSION_ROWS=rows)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout + result.stderr, '')
                self.assertEqual(self.log.read_text().splitlines(), ['RGB', *expected])
                self.assertEqual(self.editor_env.read_text().splitlines(), ['unset', 'unset'])

    def test_remote_tmux_without_feature_flag_keeps_the_normal_session_policy(self):
        self.tmux.write_text(self.tmux.read_text().replace(
            '#!/bin/sh\n', '#!/bin/sh\nif [ "$1" = -T ]; then exit 2; fi\n', 1))
        result = self.remote_command(rgb=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, '')
        self.assertEqual(self.log.read_text().splitlines(), ['new-session', '-A', '-s', '0'])
        self.assertEqual(self.editor_env.read_text().splitlines(), ['unset', 'unset'])

    def test_installed_picker_dispatches_and_embeds_its_copied_canonical_policy(self):
        checkout = self.directory / "checkout's $cash ; é"
        shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        policy = checkout / 'dalftui/linux/tmux-start.sh'
        policy.write_text("printf '%s\\n' copied-policy > \"$TEST_POLICY_LOG\"\n" + policy.read_text())
        # The remote command must embed the policy, never the local forwarder.
        (checkout / 'bin/tmux-start.sh').write_text('#!/bin/sh\nexit 99\n')
        self.install(checkout=checkout)
        installed = self.home / '.config/dalftui'
        self.assertEqual(installed.resolve(), checkout.resolve())
        ssh_log = self.directory / 'ssh-arguments'
        policy_log = self.directory / 'policy-log'
        ssh = self.bin / 'ssh'
        ssh.write_text(f'#!{sys.executable}\n' + '''import json, os, shlex, sys
with open(os.environ['TEST_SSH_LOG'], 'a', encoding='utf-8') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if '-G' in sys.argv:
    print('user alice')
    sys.exit(0)
if '-T' in sys.argv:
    # Model a remote host without editor integration, without opening SSH.
    sys.exit(3)
# Script generation has finished. Hide the disposable desktop policy and run
# with an empty remote home, so a reference to either checkout cannot work.
os.rename(os.environ['TEST_CANONICAL_POLICY'], os.environ['TEST_CANONICAL_POLICY'] + '.unavailable')
os.environ['HOME'] = os.environ['TEST_REMOTE_HOME']
os.environ['XDG_CONFIG_HOME'] = ''
os.execv(os.environ['TEST_SH'], shlex.split(sys.argv[-1]))
''')
        ssh.chmod(0o755)
        self.tmux.write_text(self.tmux.read_text() + 'exit 23\n')
        outside = self.directory / 'unrelated directory'
        outside.mkdir()
        remote_home = self.directory / 'remote without dalftui'
        remote_home.mkdir()
        env = dict(self.env, TEST_SSH_LOG=str(ssh_log), TEST_POLICY_LOG=str(policy_log),
                   TEST_SH=str(self.bin / 'sh'), TEST_CANONICAL_POLICY=str(policy),
                   TEST_REMOTE_HOME=str(remote_home), PYTHONPATH=str(ROOT))
        host = "alice@prod-é;$(probe)'"
        result = self.real_run([sys.executable, str(installed / 'bin/ssh_picker.py'),
                                '--connect', host, '--bridge', 'tcp'],
                               cwd=outside, env=env, input='', capture_output=True,
                               text=True, timeout=5)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn(f'SSH to {host} ended with status 23.', result.stdout)
        commands = [json.loads(line) for line in ssh_log.read_text().splitlines()]
        self.assertEqual(len(commands), 3)
        for command in commands:
            self.assertEqual(command[command.index('--') + 1], host)
        self.assertEqual(self.log.read_text().splitlines(), ['new-session', '-A', '-s', '0'])
        self.assertEqual(policy_log.read_text(), 'copied-policy\n')
        self.assertFalse(policy.exists())
        self.assertFalse((remote_home / '.config/dalftui').exists())
        self.assertEqual(self.editor_env.read_text().splitlines(), ['unset', 'unset'])

    def test_installed_dalftui_prepares_credentials_before_starting_a_listener(self):
        self.install()
        prepared, bridge = self.prepare()
        self.assertTrue(prepared)
        self.assertEqual(Path(bridge.remote_token_file).read_text(encoding='utf-8'), bridge.token + '\n')

    def test_custom_absolute_config_directory_is_detected(self):
        config = self.directory / "custom config's directory"
        self.env['XDG_CONFIG_HOME'] = str(config)
        self.install(config)
        prepared, bridge = self.prepare()
        self.assertTrue(prepared)
        self.assertTrue(Path(bridge.remote_token_file).is_file())

    def test_relative_config_directory_uses_default_like_the_installer(self):
        self.env['XDG_CONFIG_HOME'] = 'relative-config'
        self.install()
        prepared, _ = self.prepare()
        self.assertTrue(prepared)

    def test_missing_tmux_skips_bridge_even_with_dalftui_installed(self):
        self.install()
        self.tmux.rename(self.bin / 'disabled-tmux')
        prepared, bridge = self.prepare()
        self.assertFalse(prepared)
        self.assertFalse(Path(bridge.remote_directory).exists())

    def assert_update_suggestion_without_bridge(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            prepared, bridge = self.prepare()
        self.assertFalse(prepared)
        self.assertFalse(Path(bridge.remote_directory).exists())
        self.assertIn('https://github.com/dalf/dalftui', output.getvalue())
        self.assertNotIn(bridge.token, output.getvalue())
        result = self.remote_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.log.read_text().splitlines(), ['new-session', '-A', '-s', '0'])
        self.assertEqual(self.editor_env.read_text().splitlines(), ['unset', 'unset'])

    def test_unversioned_remote_dalftui_suggests_github_update_and_keeps_tmux(self):
        self.install_test_checkout()
        self.assert_update_suggestion_without_bridge()

    def test_unsupported_remote_protocol_suggests_github_update_and_keeps_tmux(self):
        self.install_test_checkout(999)
        self.assert_update_suggestion_without_bridge()

    def test_malformed_remote_protocol_suggests_github_update_and_keeps_tmux(self):
        self.install_test_checkout('unknown')
        self.assert_update_suggestion_without_bridge()

    def test_missing_remote_python_skips_bridge_and_keeps_tmux(self):
        self.install()
        (self.bin / 'python3').unlink()
        self.assert_update_suggestion_without_bridge()

    def test_broken_installation_skips_bridge(self):
        config = self.home / '.config'
        config.mkdir()
        (config / 'dalftui').symlink_to(self.directory / 'missing-checkout')
        prepared, bridge = self.prepare()
        self.assertFalse(prepared)
        self.assertFalse(Path(bridge.remote_directory).exists())

    def test_credential_setup_errors_remain_visible(self):
        self.install()
        (self.bin / 'mkdir').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Could not prepare'):
            self.prepare()


class TerminalColorTests(unittest.TestCase):
    def test_ssh_color_hints_require_a_known_capability(self):
        for env, expected in (({}, False),
                              ({'TERM': 'xterm-256color'}, False),
                              ({'COLORTERM': 'truecolor'}, True),
                              ({'COLORTERM': '24bit'}, True),
                              ({'WT_SESSION': 'terminal-session'}, True),
                              ({'TERM_PROGRAM': 'Apple_Terminal', 'COLORTERM': 'truecolor'}, False),
                              ({'TERM_PROGRAM': 'Apple_Terminal', 'WT_SESSION': 'stale'}, False)):
            with self.subTest(env=env):
                self.assertEqual(picker.terminal_supports_rgb(env), expected)

    def test_connect_carries_a_tty_capability_hint_to_only_the_attachment(self):
        if sys.platform == 'win32':
            from dalftui.windows import ssh as terminal
        else:
            from dalftui.linux import ssh_picker as terminal

        class TerminalOutput(io.StringIO):
            def isatty(self):
                return True

        output = TerminalOutput()
        with (patch.dict(os.environ, {'WT_SESSION': 'terminal-session', 'TERM_PROGRAM': ''}),
              patch.object(picker, 'configured_login', return_value='alice'),
              patch.object(picker, 'EditorBridge'),
              patch.object(picker, 'prepare_editor_credentials', return_value=False),
              patch.object(terminal, 'set_terminal_title'),
              patch.object(picker, 'ssh_command', return_value=['ssh']) as command,
              patch.object(picker.subprocess, 'run',
                           return_value=subprocess.CompletedProcess(['ssh'], 0)),
              redirect_stdout(output)):
            self.assertEqual(picker.connect('server'), 0)
        command.assert_called_once_with('server', None, rgb=True)


if __name__ == '__main__':
    unittest.main()
