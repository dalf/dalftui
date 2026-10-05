"""Terminal-independent host grid, filtering, and keyboard navigation."""
from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class HostAction:
    host: str
    mode: str
    check: str | None = None


def cell_width(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
               for char in text if char.isprintable())


def clip(text, width):
    """Clip by terminal cells, excluding control characters from terminal output."""
    result, used = [], 0
    for char in text:
        if not char.isprintable():
            continue
        size = cell_width(char)
        if used + size > width:
            break
        result.append(char)
        used += size
    return ''.join(result)


def filtered_hosts(hosts, query):
    """Match each whitespace-separated term as a case-insensitive subsequence."""
    terms = query.casefold().split()

    def matches(host):
        folded = host.casefold()
        for term in terms:
            remaining = iter(folded)
            if not all(any(char == candidate for candidate in remaining) for char in term):
                return False
        return True

    return [host for host in hosts if matches(host)]


@dataclass(frozen=True)
class Layout:
    rows: int
    columns: int
    width: int

    @property
    def capacity(self):
        return self.rows * self.columns


def layout(hosts, width, height):
    rows = max(1, height - 6)
    usable = max(1, width - 2)
    desired = max((cell_width(host) + 4 for host in hosts), default=18)
    columns = min(max(1, usable // desired), max(1, (len(hosts) + rows - 1) // rows))
    return Layout(rows, columns, usable // columns)


class Picker:
    def __init__(self, hosts):
        self.hosts = list(hosts)
        self.query = ''
        self.matches = self.hosts[:]
        self.selected = 0
        self.message = ''

    def update(self, key, grid):
        steps = {'up': -1, 'down': 1, 'left': -grid.rows, 'right': grid.rows,
                 'page_up': -grid.capacity, 'page_down': grid.capacity,
                 'tab': 1, 'back_tab': -1}
        if key in steps:
            self.selected += steps[key]
        elif key == 'home':
            self.selected = 0
        elif key == 'end':
            self.selected = len(self.matches) - 1
        else:
            previous = self.query
            if key == 'backspace':
                self.query = self.query[:-1]
            elif key == 'clear':
                self.query = ''
            elif len(key) == 1 and key.isprintable():
                self.query += key
            if self.query != previous:
                self.matches = filtered_hosts(self.hosts, self.query)
                self.selected = 0
                self.message = ''
        self.selected = max(0, min(self.selected, len(self.matches) - 1))

    def frame(self, width, height, action):
        grid = layout(self.matches, width, height)
        cells = []

        def write(y, x, text, style='normal', limit=None):
            # Leave the last terminal cell unused to prevent auto-wrapping.
            if 0 <= y < height and 0 <= x < width - 1:
                budget = width - 1 - x
                cells.append((y, x, clip(text, min(budget, limit) if limit is not None else budget), style))

        if height < 7 or width < 12:
            write(0, 0, 'Enlarge terminal | Esc cancels')
            return grid, cells
        write(0, 1, f'SSH HOSTS  {len(self.matches)}/{len(self.hosts)}', 'heading')
        write(1, 1, f'F4 actions | Enter {action} | Arrows select | Esc cancel', 'muted')
        # Show the end of a long query without moving the grid outside the screen.
        query = self.query
        while query and cell_width(query) > max(1, width - 11):
            query = query[1:]
        write(2, 1, f'Filter: {query}', 'heading')
        write(3, 1, 'Ctrl+O connect typed hostname, IP or user@host', 'muted')
        start = self.selected // grid.capacity * grid.capacity
        stop = min(len(self.matches), start + grid.capacity)
        if not self.matches:
            write(4, 1, 'No matches. Ctrl+O connects to the typed destination.', 'muted')
        for index in range(start, stop):
            offset = index - start
            y, x = 4 + offset % grid.rows, 1 + offset // grid.rows * grid.width
            selected = index == self.selected
            label = ('> ' if selected else '  ') + self.matches[index]
            write(y, x, label, 'selected' if selected else 'normal', grid.width - 1)
        pages = max(1, (len(self.matches) + grid.capacity - 1) // grid.capacity)
        write(height - 2, 1,
              f'{grid.columns} column(s) | {start + 1 if self.matches else 0}-{stop}'
              f' of {len(self.matches)} | Page {start // grid.capacity + 1}/{pages}'
              ' | PgUp/PgDn | Ctrl+U clear', 'muted')
        detail = self.message or (self.matches[self.selected] if self.matches else 'Type a hostname, IP address or user@host.')
        write(height - 1, 1, detail, 'heading')
        return grid, cells


def dialog(screen, title, lines, *, choose=False):
    """Scrollable text or single-column menu; Esc always returns to its caller."""
    selected = 0
    previous = None
    while True:
        width, height = screen.size()
        visible_lines = list(lines)
        if not choose:
            visible_lines = []
            for line in lines:
                line = ''.join(char for char in line if char.isprintable())
                while cell_width(line) > max(2, width - 4):
                    part = clip(line, max(2, width - 4))
                    visible_lines.append(part)
                    line = line[len(part):]
                visible_lines.append(line)
        rows = max(1, height - 4)
        selected = max(0, min(selected, len(visible_lines) - 1))
        start = selected // rows * rows
        help_text = ('Enter select | ' if choose else 'Enter back | ') + 'Esc back | Arrows / PgUp / PgDn'
        cells = [(0, 1, title, 'heading'), (1, 1, help_text, 'muted')]
        for index, line in enumerate(visible_lines[start:start + rows], start):
            active = choose and index == selected
            cells.append((2 + index - start, 1, ('> ' if active else '  ') + line,
                          'selected' if active else 'normal'))
        cells.append((height - 1, 1, f'{start + 1 if visible_lines else 0}-{min(start + rows, len(visible_lines))} / {len(visible_lines)}', 'muted'))
        frame = [(y, x, clip(text, width - x - 1), style)
                 for y, x, text, style in cells if 0 <= y < height and x < width - 1]
        if (width, height, frame) != previous:
            screen.draw(frame)
            previous = (width, height, frame)
        key = screen.read_key()
        if key in ('cancel', 'eof') or (key == 'enter' and not choose):
            return None
        if key == 'enter' and lines:
            return selected
        steps = {'up': -1, 'down': 1, 'tab': 1, 'back_tab': -1,
                 'page_up': -rows, 'page_down': rows}
        if key in steps:
            selected += steps[key]
        elif key == 'home':
            selected = 0
        elif key == 'end':
            selected = len(visible_lines) - 1


def host_actions(screen, host, details, checks):
    labels = ['Connect normally', 'Show connection details', 'Connect without tmux',
              'Run a saved check', 'Open ops mode']
    while True:
        choice = dialog(screen, f'HOST ACTIONS: {host}', labels, choose=True)
        if choice is None:
            return None
        if choice == 0:
            return host
        if choice in (2, 4):
            return HostAction(host, 'plain' if choice == 2 else 'ops')
        try:
            if choice == 1:
                width, _ = screen.size()
                screen.draw([(0, 0, clip('Reading SSH connection details...', max(0, width - 1)), 'heading')])
                dialog(screen, f'CONNECTION DETAILS: {host}', details(host))
            else:
                available = checks(host)
                choice = dialog(screen, f'SAVED CHECKS: {host}',
                                [f'{check.name} ({check.timeout}s)' for check in available], choose=True)
                if choice is not None:
                    check = available[choice]
                    return HostAction(host, 'check', check.name)
        except (OSError, RuntimeError, ValueError) as error:
            dialog(screen, 'Could not load host action', str(error).splitlines())


def pick(screen, hosts, validate, *, action='connect', details=None, checks=None):
    """Use normalized screen keys; validate with require_tag=False for Ctrl+O."""
    picker = Picker(hosts)
    previous = None
    while True:
        width, height = screen.size()
        grid, cells = picker.frame(width, height, action)
        frame = (width, height, cells)
        if frame != previous:
            screen.draw(cells)
            previous = frame
        key = screen.read_key()
        if key in ('cancel', 'eof'):
            return None
        if key == 'actions' and details is not None and checks is not None:
            host = picker.matches[picker.selected] if picker.matches else picker.query
            picker.message = validate(host, require_tag=False)
            if not picker.message:
                selected = host_actions(screen, host, details, checks)
                if selected:
                    return selected
                previous = None
            continue
        if key in ('enter', 'connect_typed'):
            if key == 'enter' and picker.matches:
                return picker.matches[picker.selected]
            if picker.query or key == 'connect_typed':
                try:
                    picker.message = (validate(picker.query, require_tag=False)
                                      if key == 'connect_typed' else validate(picker.query))
                except RuntimeError as error:
                    picker.message = str(error)
                if not picker.message:
                    return picker.query
        elif key:
            picker.update(key, grid)
