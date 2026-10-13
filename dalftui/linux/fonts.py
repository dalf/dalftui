"""Install the pinned Hack Nerd Font Mono release for the local desktop user.

The archive is downloaded only when the user's copy is missing or different. Its
SHA-256 digest and every installed member are pinned below, and members are read
by exact name without extracting the archive to disk.
"""
from dataclasses import dataclass
import hashlib
import hmac
import http.client
import io
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

try:
    import lzma
except ImportError:  # Some self-built Pythons lack liblzma; dependencies() reports it.
    lzma = None

FAMILY = 'Hack Nerd Font Mono'
DIRECTORY = 'HackNerdFontMono'
LIMIT = 8 * 1024 * 1024
TIMEOUT = 60
HINT = ('Check that fontconfig includes the user font directory, or rerun ./install; '
        'use ./install --no-fonts to skip this step.')


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    sha256: str
    size: int  # Exact archive size; downloads and local archives are capped at it.
    files: tuple  # (name, sha256) pairs installed into the font directory.
    styles: tuple  # (fontconfig style, file name) pairs that must resolve.


HACK = Release(
    version='v3.5.1',
    url='https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/Hack.tar.xz',
    sha256='cdd389472e10e2261520140ff1b382b4f8a226af5fd0b2735b975d31151d9c3c',
    size=2781192,
    files=(
        ('HackNerdFontMono-Regular.ttf', 'e5aeb58577a8acf2b42083e4a07ce48bd53116fdd868636403cadb5b547351be'),
        ('HackNerdFontMono-Bold.ttf', '7c2c76c26ff80fb546798b204ae519335573417c969eb3142d202298722d3832'),
        ('HackNerdFontMono-Italic.ttf', '7b45fbee724e4a58bca6e23d176006d6334cdc848d0ec53ec38daef252900fa8'),
        ('HackNerdFontMono-BoldItalic.ttf', 'ad9e8d4504c0ffaab07ff44bb98cc0cfd67655df9cda97f5c9fc15e77b301497'),
        ('LICENSE.md', '1f61bb7c790c59b4b0ecdf304628b94e42ae4c8020094a8c3da73381ab212623'),
    ),
    styles=(
        ('Regular', 'HackNerdFontMono-Regular.ttf'),
        ('Bold', 'HackNerdFontMono-Bold.ttf'),
        ('Italic', 'HackNerdFontMono-Italic.ttf'),
        ('Bold Italic', 'HackNerdFontMono-BoldItalic.ttf'),
    ),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def outdated(directory, release=None):
    """Return pinned file names that are missing or differ, without network access."""
    release = release or HACK
    directory = Path(directory)
    if (directory.exists() or directory.is_symlink()) and not directory.is_dir():
        raise ValueError(f'Refusing to replace a file with the font directory: {directory}')
    result = []
    for name, expected in release.files:
        path = directory / name
        if path.is_symlink():
            result.append(name)
        elif not path.exists():
            result.append(name)
        elif not path.is_file():
            raise ValueError(f'Refusing to replace a directory or special file: {path}')
        elif not hmac.compare_digest(digest(path.read_bytes()), expected):
            result.append(name)
    return result


class HttpsRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only while they stay on HTTPS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise ValueError(f'Refusing a font download redirect away from HTTPS: {newurl}')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit=LIMIT, *, timeout=TIMEOUT, opener=None):
    """Download at most limit bytes over HTTPS."""
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError(f'Font downloads require HTTPS: {url}')
    opener = opener or urllib.request.build_opener(HttpsRedirects)
    request = urllib.request.Request(url, headers={'User-Agent': 'dalftui-install'})
    try:
        with opener.open(request, timeout=timeout) as response:
            final = response.geturl()
            if urllib.parse.urlsplit(final).scheme != 'https':
                raise ValueError(f'Font download left HTTPS: {final}')
            length = response.headers.get('Content-Length')
            if length and length.isdigit() and int(length) > limit:
                raise ValueError(f'Font download exceeds {limit} bytes: {url}')
            chunks = []
            total = 0
            while chunk := response.read(64 * 1024):
                total += len(chunk)
                if total > limit:
                    raise ValueError(f'Font download exceeds {limit} bytes: {url}')
                chunks.append(chunk)
    except http.client.HTTPException as error:
        raise OSError(f'Font download failed: {error!r}') from error
    except urllib.error.URLError as error:
        raise OSError(f'Font download failed from {url}: {error.reason}') from error
    return b''.join(chunks)


def read_archive(path, limit=LIMIT):
    """Read a local copy of the release archive, applying the download size cap."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'Font archive is not a regular file: {path}')
    if path.stat().st_size > limit:
        raise ValueError(f'Font archive exceeds {limit} bytes: {path}')
    return path.read_bytes()


def extract(release, data):
    """Return {name: bytes} for the pinned members only; nothing is written to disk."""
    if len(data) != release.size or not hmac.compare_digest(digest(data), release.sha256):
        raise ValueError(f'Font archive checksum mismatch; expected {release.version} '
                         f'SHA-256 {release.sha256} ({release.size} bytes).')
    errors = (tarfile.TarError, EOFError) + ((lzma.LZMAError,) if lzma else ())
    result = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as archive:
            for name, expected in release.files:
                try:
                    member = archive.getmember(name)
                except KeyError:
                    raise ValueError(f'Font archive lacks {name}.') from None
                if not member.isreg():
                    raise ValueError(f'Font archive member is not a regular file: {name}')
                stream = archive.extractfile(member)
                content = stream.read() if stream else b''
                if not hmac.compare_digest(digest(content), expected):
                    raise ValueError(f'Font archive member checksum mismatch: {name}')
                result[name] = content
    except errors as error:
        raise ValueError(f'Cannot read the font archive: {error}') from error
    return result


def run(*argv):
    """Run a fontconfig command; tests replace this function.

    Output is decoded like file names, so a non-UTF-8 font path cannot abort setup.
    """
    return subprocess.run(argv, capture_output=True, text=True, errors='surrogateescape',
                          timeout=TIMEOUT)


def refresh(directory):
    # The exit status is ignored: verify() checks what fontconfig actually resolves.
    run('fc-cache', '-f', str(directory))


def listed(family=FAMILY):
    """Map each real font path fontconfig lists for family to its style names."""
    result = run('fc-list', '-f', '%{file}\t%{style}\n', f':family={family}')
    fonts = {}
    for line in result.stdout.splitlines():
        file, _, styles = line.partition('\t')
        if file:
            names = {item.strip().casefold() for item in styles.split(',') if item.strip()}
            fonts.setdefault(os.path.realpath(file), set()).update(names)
    return fonts


def matches(style, family=FAMILY):
    result = run('fc-match', '-f', '%{family}\n', f'{family}:style={style}')
    families = {item.strip().casefold() for line in result.stdout.splitlines()
                for item in line.split(',')}
    return result.returncode == 0 and family.casefold() in families


def verify(directory, release=None):
    """Require fontconfig to list every installed style and resolve the family."""
    release = release or HACK
    fonts = listed()
    unlisted = [name for _, name in release.styles
                if os.path.realpath(Path(directory) / name) not in fonts]
    if unlisted:
        raise RuntimeError(f'fontconfig does not list {", ".join(unlisted)} from {directory}. {HINT}')
    unresolved = [style for style, _ in release.styles if not matches(style)]
    if unresolved:
        raise RuntimeError(f'fontconfig does not resolve {FAMILY} for {", ".join(unresolved)}. {HINT}')


def external(directory, release=None):
    """Return font files outside directory when they cover every pinned style."""
    release = release or HACK
    own = os.path.realpath(directory)
    try:
        fonts = listed()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return []
    others = {path: styles for path, styles in fonts.items()
              if not Path(path).is_relative_to(own)}
    covered = set().union(*others.values()) if others else set()
    if all(style.casefold() in covered for style, _ in release.styles):
        return sorted(others)
    return []


def resolves():
    """Cheap reload check; an unavailable fontconfig is not reported."""
    try:
        return matches('Regular')
    except (OSError, subprocess.SubprocessError):
        return True
