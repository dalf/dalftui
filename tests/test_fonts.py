"""Test the pinned font download, archive checks, and fontconfig verification offline."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dalftui.linux import fonts

FAKE_FILES = {name: f'fake {name} for dalftui tests\n'.encode() for name, _ in fonts.HACK.files}
TEST_URL = 'https://example.invalid/nerd-fonts/Hack.tar.xz'


def tar_member(name, content=b'', kind=tarfile.REGTYPE, linkname=''):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.mode = 0o644
    info.linkname = linkname
    info.size = len(content) if kind == tarfile.REGTYPE else 0
    return info, content


def build_archive(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:xz') as archive:
        for info, content in members:
            archive.addfile(info, io.BytesIO(content) if info.isreg() else None)
    return buffer.getvalue()


def synthetic_release(files=None, members=None, *, pinned=None):
    """Build an in-memory tar.xz and a release whose pins match its fake members."""
    files = dict(FAKE_FILES if files is None else files)
    if members is None:
        members = [tar_member(name, content) for name, content in files.items()]
    data = build_archive(members)
    pinned = files if pinned is None else pinned
    release = fonts.Release(
        version='v0.0.0-test', url=TEST_URL, sha256=fonts.digest(data), size=len(data),
        files=tuple((name, fonts.digest(content)) for name, content in pinned.items()),
        styles=fonts.HACK.styles)
    return release, data


class FakeFontconfig:
    """Answer fc-cache, fc-list and fc-match from files actually present.

    fc-cache records the pinned fonts in the refreshed directory; fc-list and
    fc-match report cached fonts that still exist plus any simulated system copy.
    """

    def __init__(self, release=None):
        self.release = release or fonts.HACK
        self.cache = {}
        self.system = {}
        self.calls = []
        self.broken = False

    def install_system_copy(self, directory, styles=None):
        directory = Path(directory)
        for style, name in self.release.styles:
            if styles is None or style in styles:
                self.system[str(directory / name)] = {style}

    def fonts(self):
        present = {path: styles for path, styles in self.cache.items() if os.path.exists(path)}
        present.update(self.system)
        return present

    def __call__(self, *argv):
        self.calls.append(argv)
        program = argv[0]
        if program == 'fc-cache':
            directory = Path(argv[-1])
            names = {name: style for style, name in self.release.styles}
            if not self.broken and directory.is_dir():
                for path in directory.iterdir():
                    if path.name in names:
                        self.cache[os.path.realpath(path)] = {names[path.name]}
            return subprocess.CompletedProcess(argv, 0, '', '')
        if program == 'fc-list':
            assert argv[-1] == f':family={fonts.FAMILY}', argv
            output = ''.join(f'{path}\t{",".join(sorted(styles))}\n'
                             for path, styles in self.fonts().items())
            return subprocess.CompletedProcess(argv, 0, output, '')
        if program == 'fc-match':
            family, _, style = argv[-1].partition(':style=')
            assert family == fonts.FAMILY, argv
            found = any(style in styles for styles in self.fonts().values())
            output = (fonts.FAMILY if found else 'DejaVu Sans Mono,DejaVu Sans') + '\n'
            return subprocess.CompletedProcess(argv, 0, output, '')
        raise AssertionError(f'Unexpected command: {argv}')

    def programs(self):
        return [call[0] for call in self.calls]


class Response:
    def __init__(self, data, url=TEST_URL, length=True):
        self.stream = io.BytesIO(data)
        self.url = url
        self.headers = {'Content-Length': str(len(data))} if length else {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, size):
        return self.stream.read(size)


class Opener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


class PinTests(unittest.TestCase):
    def test_release_pins_are_consistent(self):
        release = fonts.HACK
        self.assertTrue(release.url.startswith(
            f'https://github.com/ryanoasis/nerd-fonts/releases/download/{release.version}/'))
        self.assertTrue(release.url.endswith('/Hack.tar.xz'))
        self.assertLessEqual(release.size, fonts.LIMIT)
        names = [name for name, _ in release.files]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('LICENSE.md', names)
        for value in [release.sha256, *(item for _, item in release.files)]:
            self.assertRegex(value, r'\A[0-9a-f]{64}\Z')
        self.assertEqual([style for style, _ in release.styles],
                         ['Regular', 'Bold', 'Italic', 'Bold Italic'])
        for _, name in release.styles:
            self.assertIn(name, names)
            self.assertTrue(name.startswith(fonts.DIRECTORY + '-') and name.endswith('.ttf'))

    def test_shared_alacritty_configuration_selects_the_installed_family(self):
        config = tomllib.loads((ROOT / 'config/alacritty.toml').read_text(encoding='utf-8'))
        self.assertEqual(config['font']['normal']['family'], fonts.FAMILY)
        self.assertEqual(config['font']['size'], 10.5)


class ExtractTests(unittest.TestCase):
    def test_only_pinned_members_are_returned(self):
        decoys = [tar_member('../HackNerdFontMono-Regular.ttf', b'escape'),
                  tar_member('/tmp/HackNerdFontMono-Bold.ttf', b'absolute'),
                  tar_member('nested/HackNerdFontMono-Italic.ttf', b'nested'),
                  tar_member('HackNerdFont-Regular.ttf', b'other family'),
                  tar_member('README.md', b'readme'),
                  tar_member('link-to-passwd', kind=tarfile.SYMTYPE, linkname='/etc/passwd')]
        members = decoys + [tar_member(name, content) for name, content in FAKE_FILES.items()]
        release, data = synthetic_release(members=members)
        with tempfile.TemporaryDirectory() as directory:
            before = os.getcwd()
            os.chdir(directory)
            try:
                result = fonts.extract(release, data)
            finally:
                os.chdir(before)
            self.assertEqual(os.listdir(directory), [])
        self.assertEqual(result, FAKE_FILES)

    def test_link_members_with_pinned_names_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            with self.subTest(kind=kind):
                members = [tar_member(name, content) for name, content in FAKE_FILES.items()
                           if name != 'HackNerdFontMono-Bold.ttf']
                members.append(tar_member('HackNerdFontMono-Bold.ttf', kind=kind, linkname='/etc/passwd'))
                release, data = synthetic_release(members=members)
                with self.assertRaisesRegex(ValueError, 'not a regular file: HackNerdFontMono-Bold.ttf'):
                    fonts.extract(release, data)

    def test_archive_checksum_mismatch_is_rejected(self):
        release, data = synthetic_release()
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            fonts.extract(release, data + b'\0')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            fonts.extract(fonts.HACK, data)

    def test_archive_size_must_match_the_pin(self):
        release, data = synthetic_release()
        wrong = fonts.Release(release.version, release.url, release.sha256, release.size + 1,
                              release.files, release.styles)
        with self.assertRaisesRegex(ValueError, f'checksum mismatch.*{release.size + 1} bytes'):
            fonts.extract(wrong, data)

    def test_member_checksum_mismatch_is_rejected(self):
        pinned = dict(FAKE_FILES, **{'HackNerdFontMono-Italic.ttf': b'expected content'})
        release, data = synthetic_release(pinned=pinned)
        with self.assertRaisesRegex(ValueError, 'member checksum mismatch: HackNerdFontMono-Italic.ttf'):
            fonts.extract(release, data)

    def test_missing_member_is_rejected(self):
        files = {name: content for name, content in FAKE_FILES.items() if name != 'LICENSE.md'}
        release, data = synthetic_release(files=files, pinned=FAKE_FILES)
        with self.assertRaisesRegex(ValueError, 'lacks LICENSE.md'):
            fonts.extract(release, data)

    def test_unreadable_archive_is_a_value_error(self):
        complete = build_archive([tar_member(name, content * 4096) for name, content in FAKE_FILES.items()])
        for data in (b'not an xz archive', complete[:len(complete) // 2]):
            with self.subTest(data=data[:8]):
                release = fonts.Release('v0', TEST_URL, fonts.digest(data), len(data),
                                        tuple((name, fonts.digest(content)) for name, content in FAKE_FILES.items()),
                                        fonts.HACK.styles)
                with self.assertRaisesRegex(ValueError, 'Cannot read the font archive'):
                    fonts.extract(release, data)

    def test_local_archive_respects_the_size_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Hack.tar.xz'
            path.write_bytes(b'x' * 11)
            self.assertEqual(fonts.read_archive(path, 11), b'x' * 11)
            with self.assertRaisesRegex(ValueError, 'exceeds 10 bytes'):
                fonts.read_archive(path, 10)
            with self.assertRaisesRegex(ValueError, 'not a regular file'):
                fonts.read_archive(Path(directory), 10)


class FetchTests(unittest.TestCase):
    def test_download_is_read_with_user_agent_and_timeout(self):
        opener = Opener(Response(b'archive'))
        self.assertEqual(fonts.fetch(TEST_URL, 100, timeout=7, opener=opener), b'archive')
        request, timeout = opener.requests[0]
        self.assertEqual(timeout, 7)
        self.assertEqual(request.full_url, TEST_URL)
        self.assertEqual(request.get_header('User-agent'), 'dalftui-install')

    def test_non_https_urls_are_rejected_before_opening(self):
        opener = Opener(Response(b'archive'))
        for url in ('http://example.invalid/Hack.tar.xz', 'file:///etc/passwd', 'ftp://example.invalid/x'):
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, 'HTTPS'):
                    fonts.fetch(url, 100, opener=opener)
        self.assertEqual(opener.requests, [])

    def test_redirects_must_stay_on_https(self):
        opener = Opener(Response(b'archive', url='http://example.invalid/Hack.tar.xz'))
        with self.assertRaisesRegex(ValueError, 'left HTTPS'):
            fonts.fetch(TEST_URL, 100, opener=opener)
        handler = fonts.HttpsRedirects()
        request = urllib.request.Request(TEST_URL)
        with self.assertRaisesRegex(ValueError, 'away from HTTPS'):
            handler.redirect_request(request, None, 302, 'Found', {}, 'http://example.invalid/x')
        followed = handler.redirect_request(request, None, 302, 'Found', {}, 'https://example.invalid/y')
        self.assertEqual(followed.full_url, 'https://example.invalid/y')

    def test_default_opener_refuses_insecure_redirects(self):
        opener = urllib.request.build_opener(fonts.HttpsRedirects)
        self.assertTrue(any(isinstance(handler, fonts.HttpsRedirects) for handler in opener.handlers))
        self.assertFalse(any(type(handler) is urllib.request.HTTPRedirectHandler for handler in opener.handlers))

    def test_oversized_downloads_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exceeds 10 bytes'):
            fonts.fetch(TEST_URL, 10, opener=Opener(Response(b'x' * 11)))
        with self.assertRaisesRegex(ValueError, 'exceeds 10 bytes'):
            fonts.fetch(TEST_URL, 10, opener=Opener(Response(b'x' * 200_000, length=False)))
        self.assertEqual(fonts.fetch(TEST_URL, 10, opener=Opener(Response(b'x' * 10, length=False))), b'x' * 10)

    def test_network_errors_are_os_errors(self):
        with self.assertRaisesRegex(OSError, 'Font download failed'):
            fonts.fetch(TEST_URL, 10, opener=Opener(error=urllib.error.URLError('offline')))


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dalftui-fonts-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / 'fonts' / fonts.DIRECTORY
        self.release, _ = synthetic_release()
        self.names = [name for name, _ in self.release.files]

    def populate(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        for name, content in FAKE_FILES.items():
            (self.directory / name).write_bytes(content)

    def test_outdated_reports_missing_and_different_files(self):
        self.assertEqual(fonts.outdated(self.directory, self.release), self.names)
        self.populate()
        self.assertEqual(fonts.outdated(self.directory, self.release), [])
        (self.directory / 'HackNerdFontMono-Bold.ttf').write_bytes(b'other version')
        (self.directory / 'LICENSE.md').unlink()
        self.assertEqual(fonts.outdated(self.directory, self.release),
                         ['HackNerdFontMono-Bold.ttf', 'LICENSE.md'])
        self.assertEqual(fonts.outdated(self.directory, self.release), fonts.outdated(self.directory, self.release))

    @unittest.skipIf(os.name == 'nt', 'symlinks need Windows privileges')
    def test_outdated_replaces_symlinks_but_refuses_directories(self):
        self.populate()
        target = self.root / 'elsewhere.ttf'
        target.write_bytes(FAKE_FILES['HackNerdFontMono-Regular.ttf'])
        regular = self.directory / 'HackNerdFontMono-Regular.ttf'
        regular.unlink()
        regular.symlink_to(target)
        self.assertEqual(fonts.outdated(self.directory, self.release), ['HackNerdFontMono-Regular.ttf'])
        license_path = self.directory / 'LICENSE.md'
        license_path.unlink()
        license_path.mkdir()
        with self.assertRaisesRegex(ValueError, 'directory or special file'):
            fonts.outdated(self.directory, self.release)

    def test_font_directory_must_not_be_a_file(self):
        self.directory.parent.mkdir(parents=True)
        self.directory.write_text('not a directory')
        with self.assertRaisesRegex(ValueError, 'font directory'):
            fonts.outdated(self.directory, self.release)

    def test_verify_requires_listing_and_family_resolution(self):
        fontconfig = FakeFontconfig(self.release)
        self.populate()
        with patch.object(fonts, 'run', side_effect=fontconfig):
            with self.assertRaisesRegex(RuntimeError, 'does not list .*HackNerdFontMono-Regular.ttf'):
                fonts.verify(self.directory, self.release)
            fonts.refresh(self.directory)
            fonts.verify(self.directory, self.release)
            self.assertIn(('fc-cache', '-f', str(self.directory)), fontconfig.calls)
            with patch.object(fontconfig, 'fonts', side_effect=[fontconfig.fonts(), {}, {}, {}, {}]):
                with self.assertRaisesRegex(RuntimeError, 'does not resolve Hack Nerd Font Mono'):
                    fonts.verify(self.directory, self.release)

    def test_verify_does_not_accept_only_a_system_copy(self):
        fontconfig = FakeFontconfig(self.release)
        fontconfig.install_system_copy('/usr/share/fonts/truetype/hack')
        self.populate()
        with patch.object(fonts, 'run', side_effect=fontconfig):
            with self.assertRaisesRegex(RuntimeError, 'does not list'):
                fonts.verify(self.directory, self.release)

    def test_external_copy_must_cover_every_style_outside_our_directory(self):
        fontconfig = FakeFontconfig(self.release)
        self.populate()
        with patch.object(fonts, 'run', side_effect=fontconfig):
            fonts.refresh(self.directory)
            self.assertEqual(fonts.external(self.directory, self.release), [])
            fontconfig.install_system_copy('/usr/share/fonts/hack', styles=('Regular', 'Bold'))
            self.assertEqual(fonts.external(self.directory, self.release), [])
            fontconfig.install_system_copy('/usr/share/fonts/hack')
            expected = sorted(os.path.realpath(path) for path in fontconfig.system)
            self.assertEqual(fonts.external(self.directory, self.release), expected)
        with patch.object(fonts, 'run', side_effect=FileNotFoundError('fc-list')):
            self.assertEqual(fonts.external(self.directory, self.release), [])

    def test_non_utf8_font_paths_do_not_abort_reuse_detection(self):
        script = r'import sys; sys.stdout.buffer.write(b"/fonts/\x81\xff.ttf\tRegular\n")'
        result = fonts.run(sys.executable, '-c', script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('.ttf\tRegular', result.stdout)
        with patch.object(fonts, 'run', side_effect=UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'test')):
            self.assertEqual(fonts.external(self.directory, self.release), [])

    def test_external_parses_multiple_style_names(self):
        output = ''.join(f'/opt/fonts/{name}\t{style},Localized {index}\n'
                         for index, (style, name) in enumerate(self.release.styles))
        result = subprocess.CompletedProcess(['fc-list'], 0, output, '')
        with patch.object(fonts, 'run', return_value=result):
            self.assertEqual(len(fonts.external(self.directory, self.release)), 4)

    def test_resolves_is_quiet_without_fontconfig(self):
        fontconfig = FakeFontconfig(self.release)
        with patch.object(fonts, 'run', side_effect=fontconfig):
            self.assertFalse(fonts.resolves())
            fontconfig.install_system_copy('/usr/share/fonts/hack')
            self.assertTrue(fonts.resolves())
        with patch.object(fonts, 'run', side_effect=FileNotFoundError('fc-match')):
            self.assertTrue(fonts.resolves())
        with patch.object(fonts, 'run', side_effect=subprocess.TimeoutExpired('fc-match', 1)):
            self.assertTrue(fonts.resolves())


if __name__ == '__main__':
    unittest.main()
