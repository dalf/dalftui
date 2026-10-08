"""Exercise Git labels and their integration with private tmux status bars."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import subprocess
import sys
import termios
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_install as install_tests
from dalftui.linux import tmux_label


def git(folder, *arguments):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    result = subprocess.run(['git', '-C', str(folder), *arguments], env=env,
                            capture_output=True, text=True, timeout=10, check=True)
    return result.stdout.strip()


def repository(folder, *, commit=True):
    folder.mkdir(parents=True, exist_ok=True)
    git(folder, 'init', '-b', 'main')
    git(folder, 'config', 'user.name', 'Dalftui Test')
    git(folder, 'config', 'user.email', 'test@example.invalid')
    git(folder, 'config', 'commit.gpgsign', 'false')
    git(folder, 'config', 'core.hooksPath', os.devnull)
    if commit:
        (folder / 'tracked.txt').write_text('initial\n')
        git(folder, 'add', 'tracked.txt')
        git(folder, 'commit', '-m', 'Initial test commit')
    return folder


@unittest.skipUnless(shutil.which('git'), 'Git is required')
class GitLabelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-git-label-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()

    def test_subdirectory_uses_repository_name_and_follows_branch_changes(self):
        project = repository(self.directory / "project's $cash ; é")
        folder = project / 'src/nested'
        folder.mkdir(parents=True)
        self.assertEqual(tmux_label.location_label(str(folder)), f'{project.name}@main')
        git(project, 'checkout', '-b', 'feature/login')
        self.assertEqual(tmux_label.location_label(str(folder)), f'{project.name}@feature/login')

    def test_unborn_branch_and_linked_worktree(self):
        project = repository(self.directory / 'project', commit=False)
        self.assertEqual(tmux_label.location_label(str(project)), 'project@main')
        (project / 'tracked.txt').write_text('initial\n')
        git(project, 'add', 'tracked.txt')
        git(project, 'commit', '-m', 'Initial test commit')
        worktree = self.directory / 'linked worktree'
        git(project, 'worktree', 'add', '-b', 'feature/worktree', str(worktree))
        self.assertEqual(tmux_label.location_label(str(worktree)),
                         'linked worktree@feature/worktree')

    def test_detached_head_uses_exact_tag_or_short_commit(self):
        project = repository(self.directory / 'project')
        commit = git(project, 'rev-parse', '--short=7', 'HEAD')
        git(project, 'checkout', '--detach')
        self.assertEqual(tmux_label.location_label(str(project)), f'project@{commit}')
        git(project, 'tag', 'v1.0')
        self.assertEqual(tmux_label.location_label(str(project)), 'project@v1.0')

    def test_outside_git_missing_directory_and_empty_path(self):
        folder = self.directory / 'outside Git'
        folder.mkdir()
        for path, expected in ((str(folder), folder.name), (str(folder / 'missing'), 'missing'),
                               ('', '?')):
            with self.subTest(path=path):
                self.assertEqual(tmux_label.location_label(path), expected)

    def test_git_failure_or_timeout_falls_back_without_error_output(self):
        for error in (FileNotFoundError('git'), subprocess.TimeoutExpired('git', 1)):
            with self.subTest(error=error):
                with patch.object(tmux_label.subprocess, 'run', side_effect=error):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        self.assertEqual(tmux_label.main(['/some/project']), 0)
                    self.assertEqual(output.getvalue(), 'project\n')

    def test_lookup_keeps_a_dirty_index_unchanged(self):
        project = repository(self.directory / 'project')
        (project / 'tracked.txt').write_text('staged\n')
        git(project, 'add', 'tracked.txt')
        (project / 'tracked.txt').write_text('unstaged\n')
        index = project / '.git/index'
        before = index.read_bytes(), index.stat().st_mtime_ns
        self.assertEqual(tmux_label.location_label(str(project)), 'project@main')
        self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before)

    def test_launcher_resolves_symlink_and_escapes_status_text(self):
        folder = self.directory / 'hash#[fg=red]\ncontrol\x1b'
        folder.mkdir()
        launcher = self.directory / 'label.py'
        try:
            launcher.symlink_to(ROOT / 'bin/tmux_label.py')
        except OSError as error:
            self.skipTest(f'Symlinks are unavailable: {error}')
        result = subprocess.run([sys.executable, str(launcher), str(folder)],
                                cwd=self.directory, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'hash##[fg=red]control\n')
        self.assertEqual(result.stderr, '')


@unittest.skipIf(os.name == 'nt', 'tmux clients require a POSIX terminal')
@unittest.skipUnless(shutil.which('git'), 'Git is required')
class TmuxLabelTests(install_tests.TmuxFixture):
    profile = 'tmux-only'

    def setUp(self):
        super().setUp()
        self.start()
        self.do_reload()
        self.assertEqual(self.tmux('show-options', '-gv', 'status-interval'), '5')
        self.tmux('set-option', '-g', 'status-interval', '1')
        master, slave = os.openpty()
        termios.tcsetwinsize(slave, (24, 300))
        process = subprocess.Popen([*self.command, 'attach-session', '-t', 'verify'],
                                   stdin=slave, stdout=slave, stderr=slave,
                                   env=dict(self.env, TERM='xterm-256color'), start_new_session=True)
        os.close(slave)
        self.master = master

        def cleanup():
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
            finally:
                os.close(master)

        self.addCleanup(cleanup)

    def program(self, folder, name='codex', command='sleep 600'):
        return self.tmux('new-window', '-d', '-P', '-F', '#{pane_id}', '-n', name,
                         '-c', str(folder), command)

    def wait_label(self, pane, expected):
        self.tmux('select-window', '-t', pane)
        while select.select([self.master], [], [], 0)[0]:
            os.read(self.master, 65536)
        self.tmux('refresh-client')
        until = time.monotonic() + 8
        actual = ''
        output = bytearray()
        while time.monotonic() < until:
            if select.select([self.master], [], [], 0.1)[0]:
                output.extend(os.read(self.master, 65536))
            # #() results belong to the persistent status client; a fresh
            # display-message command has a separate asynchronous job cache.
            actual = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', output).decode('utf-8', errors='replace')
            if expected in actual:
                return
        self.fail(f'Expected {expected!r} in the rendered status; got {actual[-1000:]!r}')

    def test_independent_program_tabs_and_live_branch_changes(self):
        first = repository(self.directory / 'first')
        second = repository(self.directory / 'second')
        subdirectory = first / 'src'
        subdirectory.mkdir()
        codex = self.program(subdirectory)
        mc = self.program(second, 'mc')
        self.wait_label(codex, 'first@main · codex')
        self.wait_label(mc, 'second@main · mc')
        git(first, 'checkout', '-b', 'feature/live')
        self.wait_label(codex, 'first@feature/live · codex')
        self.wait_label(mc, 'second@main · mc')
        self.assertEqual(self.tmux('display-message', '-p', '-t', codex, '#{window_name}'), 'codex')
        self.tmux('rename-window', '-t', mc, 'file browser')
        self.wait_label(mc, 'second@main · file browser')

    def test_running_program_directory_changes_and_non_git_fallback(self):
        project = repository(self.directory / 'project')
        outside = self.directory / 'outside Git'
        outside.mkdir()
        control = self.directory / 'current-directory'
        control.write_text(str(project))
        script = self.directory / 'change_directory.py'
        script.write_text('import os, pathlib, sys, time\n'
                          'while True:\n'
                          '    os.chdir(pathlib.Path(sys.argv[1]).read_text())\n'
                          '    time.sleep(0.1)\n')
        pane = self.program(project, 'mc', shlex.join([sys.executable, str(script), str(control)]))
        self.wait_label(pane, 'project@main · mc')
        replacement = control.with_suffix('.next')
        replacement.write_text(str(outside))
        replacement.replace(control)
        self.wait_label(pane, 'outside Git · mc')

    def test_shell_titles_and_both_claude_carriers_keep_priority(self):
        pane = self.program(self.directory, 'shell', '/bin/sh')
        self.tmux('select-pane', '-t', pane, '-T', 'shell-repo@feature/shell')
        self.wait_label(pane, 'shell-repo@feature/shell')
        program = self.program(self.directory)
        for carrier in ('ct1 w 1234567890', 'ct2 W 1234567890'):
            with self.subTest(carrier=carrier):
                self.tmux('select-pane', '-t', program, '-T', f'claude-repo@feature/claude {carrier}')
                self.wait_label(program, 'claude-repo@feature/claude')
        self.tmux('set-option', '-g', '@cctab_window_strip', '🔵')
        strip = self.tmux('display-message', '-p', '#{E:@claude_tab_active_strip}')
        self.assertIn('#[fg=#1565c0]⬤', strip)

    def test_shell_quoting_and_literal_hashes_in_repository_names(self):
        marker = self.directory / 'must-not-exist'
        self.tmux('set-environment', '-g', 'DALFTUI_TEST_MARKER', str(marker))
        name = "repo's $(touch \"$DALFTUI_TEST_MARKER\") ; (dir) #literal"
        project = repository(self.directory / name)
        pane = self.program(project)
        self.wait_label(pane, f'{name}@main · codex')
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
