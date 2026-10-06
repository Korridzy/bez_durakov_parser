"""Streaming prefix removal and normalized, 120-codepoint visible emission."""
from collections import deque
from collections.abc import Iterator
from itertools import islice

from report_title_emphasis import Text
from report_title_work import ParseWork


class Cursor:
    """At most eleven lookahead characters, independent of the line length."""

    def __init__(self, source: Iterator[str]) -> None:
        self.source: Iterator[str] = source
        self.buffer: deque[str] = deque()

    def peek(self, width: int = 1) -> str:
        while len(self.buffer) < width:
            char = next(self.source, '')
            if not char:
                break
            self.buffer.append(char)
        return ''.join(islice(self.buffer, width))

    def take(self, width: int = 1) -> None:
        for _ in range(width):
            _ = self.buffer.popleft()


def _prefix(cursor: Cursor) -> bool:
    heading, in_list = False, False
    while cursor.peek():
        while cursor.peek().isspace():
            cursor.take()
        char = cursor.peek()
        if char == '>':
            cursor.take()
            continue
        if char == '#':
            ahead = cursor.peek(7)
            width = len(ahead) - len(ahead.lstrip('#'))
            if width <= 6 and (width == len(ahead) or ahead[width].isspace()):
                cursor.take(width)
                heading = True
                continue
        if char and char in '-+*':
            ahead = cursor.peek(2)
            if len(ahead) == 1 or ahead[1].isspace():
                cursor.take()
                in_list = True
                continue
        if char.isdigit():
            ahead = cursor.peek(11)
            width = 0
            while width < len(ahead) and ahead[width].isdigit():
                width += 1
            if (width <= 9 and width + 1 < len(ahead)
                    and ahead[width] in '.)' and ahead[width + 1].isspace()):
                cursor.take(width + 1)
                in_list = True
                continue
        break
    if in_list:
        ahead = cursor.peek(4)
        if ahead[:3] in ('[x]', '[X]', '[ ]') and (len(ahead) == 3 or ahead[3].isspace()):
            cursor.take(3)
    return heading


def short_title(source: Iterator[str], work: ParseWork, strip_prefix: bool = False) -> str:
    """Stop emitting at 120; never materialize the entire visible line."""
    cursor = Cursor(source)
    heading = _prefix(cursor) if strip_prefix else False
    output: list[str] = []
    space = False
    while len(output) < 120 and cursor.peek():
        char = cursor.peek()
        cursor.take()
        work.scan()
        if char.isspace():
            space = bool(output)
            continue
        if space:
            output.append(' ')
            space = False
        if len(output) < 120:
            output.append(char)
    title = ''.join(output).rstrip()
    if heading and len(output) < 120:
        tail = title.rstrip('#')
        if tail and tail != title and tail[-1].isspace():
            title = tail.rstrip()
    work.emitted += len(title)
    return title


def render_title(tokens: list[Text], work: ParseWork) -> tuple[str, bool, bool]:
    first_literal = False
    protected = False
    first = True
    for token in tokens:
        work.tokens += 1
        if token.hidden:
            continue
        # Delimiter residue after a resolved span is visible literal text,
        # unlike an otherwise empty scaffolding-only line.
        protected |= bool(token.left or token.right)
        value = token.render()
        work.scan(3 * len(value))  # render slice, whitespace check, meaningful-text check.
        if value.strip():
            if first:
                first_literal, first = token.literal, False
            protected |= token.literal or any(not c.isspace() and c not in '*_`~#' for c in value)

    def characters() -> Iterator[str]:
        for token in tokens:
            if token.hidden:
                continue
            for pos in range(token.left, len(token.value) - token.right):
                work.scan()
                yield token.value[pos]

    return short_title(characters(), work, not first_literal), first_literal, protected
