"""Read the active program's Git context for an asynchronous tmux tab label."""
import argparse
from pathlib import Path
import subprocess


def git_output(folder, *arguments):
    """Bound each metadata lookup and leave Git's index untouched."""
    try:
        result = subprocess.run(['git', '--no-optional-locks', '-C', folder, *arguments],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                encoding='utf-8', errors='replace', timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return result.stdout.removesuffix('\n') if result.returncode == 0 else ''


def location_label(folder):
    """Match the shell's repo@ref convention, or use the directory outside Git."""
    if not folder:
        return '?'
    fallback = Path(folder).name or folder
    root = git_output(folder, 'rev-parse', '--show-toplevel')
    if not root:
        return fallback
    reference = git_output(folder, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if not reference:
        reference = (git_output(folder, 'describe', '--tags', '--exact-match', 'HEAD')
                     or git_output(folder, 'rev-parse', '--short=7', 'HEAD'))
    name = Path(root).name or root
    return f'{name}@{reference}' if reference else name


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print a tmux pane's repository and branch or directory.")
    parser.add_argument('folder')
    args = parser.parse_args(argv)
    # A filename may contain line breaks, terminal controls or tmux style syntax.
    # Keep one printable line and escape hashes for the status-line renderer.
    label = ''.join(char for char in location_label(args.folder) if char.isprintable())
    print(label.replace('#', '##'))
    return 0
