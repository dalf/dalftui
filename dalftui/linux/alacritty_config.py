"""Read Alacritty TOML imports for the shortcut guide and configuration checks."""
import copy
import os
from pathlib import Path
import tomllib


def config_directory():
    value = os.environ.get('XDG_CONFIG_HOME')
    return Path(value) if value and Path(value).is_absolute() else Path.home() / '.config'


def config_path():
    return config_directory() / 'alacritty/alacritty.toml'


def merge(base, replacement):
    """Match Alacritty: merge tables, append arrays, replace scalar values."""
    if isinstance(base, dict) and isinstance(replacement, dict):
        result = copy.deepcopy(base)
        for key, value in replacement.items():
            result[key] = merge(result[key], value) if key in result else copy.deepcopy(value)
        return result
    if isinstance(base, list) and isinstance(replacement, list):
        return copy.deepcopy(base + replacement)
    return copy.deepcopy(replacement)


def load(path=None, *, home_dir=None, depth=0, ancestors=()):
    path = Path(path) if path is not None else config_path()
    home_dir = Path(home_dir) if home_dir is not None else Path.home()
    canonical = path.resolve()
    if canonical in ancestors or depth > 16:
        raise ValueError(f'Recursive Alacritty imports: {path}')
    data = tomllib.loads(path.read_text(encoding='utf-8'))
    imports = data.get('import', data.get('general', {}).get('import', []))
    if not isinstance(imports, list) or any(not isinstance(item, str) for item in imports):
        raise ValueError(f'Invalid Alacritty import list: {path}')
    combined = {}
    for item in imports:
        child = home_dir / item[2:] if item.startswith('~/') else Path(item)
        if not child.is_absolute():
            child = path.parent / child
        if not child.exists():
            continue  # Alacritty also skips missing imports.
        combined = merge(combined, load(child, home_dir=home_dir, depth=depth + 1,
                                       ancestors=(*ancestors, canonical)))
    return merge(combined, data)
