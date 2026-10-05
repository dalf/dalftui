"""Persistent picker cache and CLI tests, including native Windows execution."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dalftui import ssh
from dalftui.linux import ssh_picker
from dalftui.windows import ssh as windows_ssh


class HostCacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dalftui-host-cache-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.config = self.root / 'config'
        self.config.write_text('Host zeta alpha git-service\n')
        self.cache = self.root / 'cache/hosts.json'
        self.executable = self.root / 'ssh.exe'
        self.executable.write_bytes(b'fake OpenSSH')
        self.executable.chmod(0o700)
        self.tags = {'zeta': 'dalftui', 'alpha': 'dalftui', 'git-service': 'git'}
        self.enterContext(patch.object(ssh, 'SSH_CONFIG', self.config))
        self.enterContext(patch.object(ssh, 'host_cache_path', return_value=self.cache))
        self.select_ssh = self.enterContext(patch.object(ssh, 'ssh_executable', return_value=str(self.executable)))
        self.run = self.enterContext(patch.object(ssh.subprocess, 'run', side_effect=self.evaluate))

    def evaluate(self, command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, 'tag ' + self.tags.get(command[-1], 'git') + '\n', '')

    def test_unchanged_list_preserves_order_and_starts_no_ssh_processes(self):
        self.assertEqual(ssh.target_hosts(), ['zeta', 'alpha'])
        self.assertEqual(self.run.call_count, 3)
        self.run.reset_mock()
        self.assertEqual(ssh.target_hosts(), ['zeta', 'alpha'])
        self.run.assert_not_called()

    def test_successfully_empty_list_is_cached(self):
        self.tags.clear()
        self.assertEqual(ssh.target_hosts(), [])
        self.run.reset_mock()
        self.assertEqual(ssh.target_hosts(), [])
        self.run.assert_not_called()

    def test_content_change_invalidates_even_with_identical_size_and_timestamp(self):
        ssh.target_hosts()
        original = self.config.stat()
        self.config.write_text('Host beta alpha git-service\n')
        os.utime(self.config, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(self.config.stat().st_size, original.st_size)
        self.run.reset_mock()
        self.assertEqual(ssh.target_hosts(), ['alpha'])
        self.assertEqual(self.run.call_count, 3)

    def test_recursive_includes_and_new_deleted_glob_matches_invalidate(self):
        snippets = self.root / 'config.d'
        snippets.mkdir()
        self.config.write_text('Include config.d/*.conf\nHost zeta\n')
        self.assertEqual(ssh.target_hosts(), ['zeta'])
        included = snippets / 'servers.conf'
        included.write_text('Include nested.conf\n')
        nested = self.root / 'nested.conf'
        nested.write_text('Host alpha\n Tag dalftui\n')
        self.assertEqual(ssh.target_hosts(), ['alpha', 'zeta'])
        self.run.reset_mock()
        self.assertEqual(ssh.target_hosts(), ['alpha', 'zeta'])
        self.run.assert_not_called()
        nested.write_text('Host alpha\n Tag git\n')
        self.tags['alpha'] = 'git'
        self.assertEqual(ssh.target_hosts(), ['zeta'])
        self.assertEqual(self.run.call_count, 2)
        included.unlink()
        self.run.reset_mock()
        self.assertEqual(ssh.target_hosts(), ['zeta'])
        self.assertEqual(self.run.call_count, 1)

    def test_missing_literal_include_appearing_invalidates(self):
        self.config.write_text('Include later.conf\nHost zeta\n')
        self.assertEqual(ssh.target_hosts(), ['zeta'])
        (self.root / 'later.conf').write_text('Host alpha\n')
        self.assertEqual(ssh.target_hosts(), ['alpha', 'zeta'])

    def test_included_symlink_retarget_is_detected(self):
        first = self.root / 'first.conf'
        second = self.root / 'second.conf'
        first.write_text('Host alpha\n')
        second.write_text('Host zeta\n')
        link = self.root / 'included.conf'
        try:
            link.symlink_to(first)
        except OSError:
            self.skipTest('Symlink creation is unavailable')
        self.config.write_text('Include included.conf\n')
        self.assertEqual(ssh.target_hosts(), ['alpha'])
        link.unlink()
        link.symlink_to(second)
        self.assertEqual(ssh.target_hosts(), ['zeta'])

    def test_different_config_path_client_and_cache_version_invalidate(self):
        ssh.target_hosts()
        other = self.root / 'other-config'
        other.write_bytes(self.config.read_bytes())
        with patch.object(ssh, 'SSH_CONFIG', other):
            self.run.reset_mock()
            self.assertEqual(ssh.target_hosts(), ['zeta', 'alpha'])
            self.assertEqual(self.run.call_count, 3)
        ssh.target_hosts()
        self.executable.write_bytes(b'updated OpenSSH installation')
        self.run.reset_mock()
        ssh.target_hosts()
        self.assertEqual(self.run.call_count, 3)
        other_executable = self.root / 'other-ssh.exe'
        other_executable.write_bytes(self.executable.read_bytes())
        other_executable.chmod(0o700)
        self.select_ssh.return_value = str(other_executable)
        self.run.reset_mock()
        ssh.target_hosts()
        self.assertEqual(self.run.call_count, 3)
        with patch.object(ssh, 'HOST_CACHE_VERSION', ssh.HOST_CACHE_VERSION + 1):
            self.run.reset_mock()
            ssh.target_hosts()
            self.assertEqual(self.run.call_count, 3)

    def test_dynamic_or_unknown_rules_bypass_even_an_existing_cache(self):
        ssh.target_hosts()
        original_cache = self.cache.read_bytes()
        for rule in ('Match exec "echo yes"', 'Match !exec "echo no"',
                     'Match localnetwork 10.0.0.0/8', 'Match user alice',
                     'Match futurecondition something', 'Include ${CONFIG_DIR}/*.conf',
                     'Include %h.conf', r'Include "C:\config\servers.conf"',
                     'HostName %l'):
            with self.subTest(rule=rule):
                self.config.write_text('Host zeta\n' + rule + '\n')
                self.run.reset_mock()
                self.assertEqual(ssh.target_hosts(), ['zeta'])
                self.assertEqual(ssh.target_hosts(), ['zeta'])
                self.assertEqual(self.run.call_count, 2)
                self.assertEqual(self.cache.read_bytes(), original_cache)

    def test_static_match_conditions_are_cacheable(self):
        self.config.write_text('Host zeta alpha\n'
                               'Match final originalhost zeta\n Tag dalftui\n'
                               'Match host exec\n Tag git\n'
                               'Match !tagged git\n Tag dalftui\n')
        self.assertEqual(ssh.target_hosts(), ['zeta', 'alpha'])
        self.run.reset_mock()
        self.assertEqual(ssh.target_hosts(), ['zeta', 'alpha'])
        self.run.assert_not_called()

    def test_unreadable_dependencies_bypass_cache(self):
        included = self.root / 'included.conf'
        included.write_text('Host alpha\n')
        self.config.write_text('Include included.conf\nHost zeta\n')
        ssh.target_hosts()
        real_read = Path.read_text

        def read(path, *args, **kwargs):
            if path == included:
                raise PermissionError('unreadable include')
            return real_read(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read):
            self.run.reset_mock()
            ssh.target_hosts()
            ssh.target_hosts()
        self.assertEqual(self.run.call_count, 2)

    def test_corrupt_and_invalid_cache_data_recomputes(self):
        ssh.target_hosts()
        original = json.loads(self.cache.read_text())
        bad_hosts = (None, 'zeta', [42], ['unknown'], ['alpha', 'zeta'], ['zeta', 'zeta'])
        contents = [b'{broken', b'\xff', b'null', b'[]', b'{}']
        contents += [json.dumps(dict(original, hosts=value)).encode() for value in bad_hosts]
        for content in contents:
            with self.subTest(content=content):
                self.cache.write_bytes(content)
                self.run.reset_mock()
                self.assertEqual(ssh.target_hosts(), ['zeta', 'alpha'])
                self.assertEqual(self.run.call_count, 3)

    def test_probe_failure_is_not_cached_and_preserves_previous_good_cache(self):
        self.run.side_effect = subprocess.TimeoutExpired('ssh', 10)
        with self.assertRaises(RuntimeError):
            ssh.target_hosts()
        self.assertFalse(self.cache.exists())
        self.run.side_effect = self.evaluate
        ssh.target_hosts()
        original = self.cache.read_bytes()
        self.run.side_effect = subprocess.TimeoutExpired('ssh', 10)
        with self.assertRaises(RuntimeError):
            ssh.target_hosts(refresh=True)
        self.assertEqual(self.cache.read_bytes(), original)

    def test_atomic_write_failure_is_harmless_and_leaves_no_temporary_files(self):
        ssh.target_hosts()
        original = self.cache.read_bytes()
        self.config.write_text('Host zeta\n')
        with patch.object(ssh.os, 'replace', side_effect=PermissionError('read-only cache')):
            self.assertEqual(ssh.target_hosts(), ['zeta'])
        self.assertEqual(self.cache.read_bytes(), original)
        self.assertEqual(list(self.cache.parent.iterdir()), [self.cache])
        self.assertEqual(ssh.target_hosts(), ['zeta'])

    def test_unavailable_cache_directory_does_not_break_listing(self):
        self.cache.parent.write_text('a file blocks the cache directory')
        self.assertEqual(ssh.target_hosts(), ['zeta', 'alpha'])
        self.run.reset_mock()
        self.assertEqual(ssh.target_hosts(), ['zeta', 'alpha'])
        self.assertEqual(self.run.call_count, 3)

    def test_edit_during_probing_is_not_published_as_a_valid_cache(self):
        def edit(command, **kwargs):
            self.config.write_text('Host alpha\n')
            return self.evaluate(command, **kwargs)
        self.run.side_effect = edit
        ssh.target_hosts()
        self.assertFalse(self.cache.exists())
        self.run.side_effect = self.evaluate
        self.assertEqual(ssh.target_hosts(), ['alpha'])

    def test_refresh_rebuilds_and_cli_list_forwards_it(self):
        ssh.target_hosts()
        self.tags['zeta'] = 'git'
        self.run.reset_mock()
        output = io.StringIO()
        with (patch.object(sys, 'argv', ['ssh_picker.py', '--list', '--refresh-hosts']),
              redirect_stdout(output)):
            self.assertEqual(ssh.main(), 0)
        self.assertEqual(output.getvalue(), 'alpha\n')
        self.assertEqual(self.run.call_count, 3)
        self.run.reset_mock()
        self.assertEqual(ssh.target_hosts(), ['alpha'])
        self.run.assert_not_called()

    def test_refresh_reaches_both_picker_interfaces(self):
        for platform in ('win32', 'linux'):
            with self.subTest(platform=platform):
                with (patch.object(sys, 'platform', platform),
                      patch.object(sys, 'argv', ['ssh_picker.py', '--refresh-hosts']),
                      patch.object(ssh, 'pick_fzf', return_value=None) as fzf,
                      patch.object(ssh_picker, 'run_picker', return_value=0) as desktop):
                    self.assertEqual(ssh.main(), 0)
                    if platform == 'win32':
                        fzf.assert_called_once_with(refresh=True)
                    else:
                        self.assertEqual(desktop.call_args.kwargs, {'refresh': True})

    def test_cache_survives_fresh_processes_without_running_ssh_on_second_open(self):
        program = '''import json, pathlib, subprocess, sys
from unittest.mock import patch
sys.dont_write_bytecode = True
from dalftui import ssh
ssh.SSH_CONFIG = pathlib.Path(sys.argv[1])
ssh.host_cache_path = lambda: pathlib.Path(sys.argv[2])
ssh.ssh_executable = lambda: sys.argv[3]
def run(command, **kwargs):
    if sys.argv[4] == 'warm':
        raise AssertionError('Warm cache started SSH')
    return subprocess.CompletedProcess(command, 0, 'tag dalftui\\n', '')
with patch.object(subprocess, 'run', side_effect=run):
    print(json.dumps(ssh.target_hosts()))
'''
        # The fixture mocks subprocess.run in this process; use its saved native
        # implementation for independent interpreter invocations.
        for mode in ('cold', 'warm'):
            result = self.native_run([sys.executable, '-c', program, str(self.config),
                                      str(self.cache), str(self.executable), mode],
                                     cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['zeta', 'alpha', 'git-service'])

    native_run = staticmethod(subprocess.run)


class CacheLocationTests(unittest.TestCase):
    def test_windows_requires_absolute_local_app_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'LOCALAPPDATA': directory}):
                self.assertEqual(windows_ssh.host_cache_path(), Path(directory) / 'dalftui/hosts-cache.json')
        for value in ('', 'relative'):
            with patch.dict(os.environ, {'LOCALAPPDATA': value}):
                self.assertIsNone(windows_ssh.host_cache_path())

    def test_linux_uses_xdg_cache_home_or_home_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (patch.object(Path, 'home', return_value=root),
                  patch.dict(os.environ, {'XDG_CACHE_HOME': str(root / 'custom')})):
                self.assertEqual(ssh_picker.host_cache_path(), root / 'custom/dalftui/hosts-cache.json')
                for value in ('', 'relative'):
                    with patch.dict(os.environ, {'XDG_CACHE_HOME': value}):
                        self.assertEqual(ssh_picker.host_cache_path(), root / '.cache/dalftui/hosts-cache.json')


if __name__ == '__main__':
    unittest.main()
