"""Linear lookahead indexes and destination/HTML lexical scans."""
from dataclasses import dataclass
import re
from string import punctuation
from typing import Final

from report_title_work import ParseWork

BACKTICKS = re.compile(r'`+')
DESTINATION_NESTING_LIMIT: Final = 32  # Shipped micromark/GFM destination grammar.
AUTOLINK = re.compile(
    r'<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\x00-\x20<>]*|' +
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@" +
    r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?' +
    r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)>')


@dataclass(frozen=True, slots=True)
class Lookahead:
    code: dict[int, int]
    parentheses: dict[int, int]
    parentheses_depth: dict[int, int]
    square: list[int]
    opening: list[int]
    whitespace: list[int]
    linebreaks: list[int]
    nonspace: list[int]
    quotes: dict[int, int]
    tag_quotes: dict[int, int]
    angles: list[int]
    angle_open: list[int]
    comments: list[int]
    work: ParseWork


def indexes_for(text: str, work: ParseWork) -> Lookahead:
    code: dict[int, int] = {}
    last: dict[int, int] = {}
    escaped: set[int] = set()
    pos = 0
    while pos < len(text):
        work.scan()
        if text[pos] == '\\' and pos + 1 < len(text):
            work.scan()
            escaped.add(pos + 1)
            pos += 2
        else:
            pos += 1
    work.scan(len(text))
    for run in reversed(list(BACKTICKS.finditer(text))):
        work.tokens += 1
        start, end = run.span()
        width = end - start
        if width in last:
            code[start] = last[width]
        # Outside code an escape consumes just the first tick, leaving a run
        # tail. Inside code, backslashes do not escape raw closing runs.
        if start in escaped and width > 1 and width - 1 in last:
            code[start + 1] = last[width - 1]
        last[width] = start
    square = [len(text)] * (len(text) + 1)
    opening = [len(text)] * (len(text) + 1)
    nonspace = [len(text)] * (len(text) + 1)
    angles = [len(text)] * (len(text) + 1)
    angle_open = [len(text)] * (len(text) + 1)
    comments = [len(text)] * (len(text) + 1)
    quotes: dict[int, int] = {}
    tag_quotes: dict[int, int] = {}
    last_quote: dict[str, int] = {}
    last_tag_quote: dict[str, int] = {}
    for pos in range(len(text) - 1, -1, -1):
        work.scan()
        square[pos] = pos if text[pos] == ']' and pos not in escaped else square[pos + 1]
        opening[pos] = pos if text[pos] == '[' and pos not in escaped else opening[pos + 1]
        nonspace[pos] = pos if not text[pos].isspace() else nonspace[pos + 1]
        angles[pos] = pos if text[pos] == '>' and pos not in escaped else angles[pos + 1]
        angle_open[pos] = pos if text[pos] == '<' else angle_open[pos + 1]
        comments[pos] = pos if text.startswith('-->', pos) else comments[pos + 1]
        if text[pos] in "'\"":
            if text[pos] in last_tag_quote:
                tag_quotes[pos] = last_tag_quote[text[pos]]
            last_tag_quote[text[pos]] = pos
            if pos not in escaped:
                if text[pos] in last_quote:
                    quotes[pos] = last_quote[text[pos]]
                last_quote[text[pos]] = pos
    parentheses: dict[int, int] = {}
    parentheses_depth: dict[int, int] = {}
    whitespace = [0]
    linebreaks = [0]
    stack: list[tuple[int, int]] = []
    for pos, char in enumerate(text):
        work.scan()
        whitespace.append(whitespace[-1] + int(char.isspace() or ord(char) < 32))
        linebreaks.append(linebreaks[-1] + int(char in '\r\n'))
        if pos in escaped:
            continue
        if char == '(':
            stack.append((pos, 1))
        elif char == ')' and stack:
            opening_pos, depth = stack.pop()
            parentheses[opening_pos] = pos
            parentheses_depth[opening_pos] = depth
            if stack:
                parent, parent_depth = stack[-1]
                stack[-1] = parent, max(parent_depth, depth + 1)
    return Lookahead(code, parentheses, parentheses_depth, square, opening, whitespace, linebreaks, nonspace,
                     quotes, tag_quotes, angles, angle_open, comments, work)


def destination_end(text: str, start: int, indexes: Lookahead) -> int:
    """Forward consumption; balanced subexpressions and titles are O(1) jumps."""
    end = len(text)
    pos = indexes.nonspace[start + 1]
    if text[pos:pos + 1] == '<':
        close = indexes.angles[pos + 1]
        if (close == end or indexes.angle_open[pos + 1] < close
                or indexes.linebreaks[close] != indexes.linebreaks[pos]):
            return -1
        pos = close + 1
    else:
        while pos < end and not text[pos].isspace() and text[pos] != ')':
            indexes.work.scan()
            if text[pos] == '\\':
                pos += 2 if text[pos + 1:pos + 2] in punctuation and pos + 1 < end else 1
            elif text[pos] == '(':
                close = indexes.parentheses.get(pos, -1)
                if (close == -1 or indexes.whitespace[close] != indexes.whitespace[pos]
                        or indexes.parentheses_depth[pos] > DESTINATION_NESTING_LIMIT):
                    return -1
                pos = close + 1
            elif ord(text[pos]) < 32:
                return -1
            else:
                pos += 1
    destination_stop = pos
    pos = indexes.nonspace[min(pos, end)]
    if pos < end and text[pos] != ')':
        if pos == destination_stop:
            return -1
        marker = text[pos]
        if marker not in "'\"(":
            return -1
        close = indexes.parentheses.get(pos, -1) if marker == '(' else indexes.quotes.get(pos, -1)
        if close == -1:
            return -1
        pos = indexes.nonspace[close + 1]
    return pos + 1 if text[pos:pos + 1] == ')' else -1


def html_tag_end(text: str, start: int, indexes: Lookahead) -> int:
    """Names/unquoted values stop at '<'; quoted values jump via cached ends."""
    end = len(text)
    pos = start + 1
    if text[pos:pos + 1] == '/':
        pos += 1
    if pos == end or not (text[pos].isascii() and text[pos].isalpha()):
        return -1
    while pos < end and text[pos].isascii() and (text[pos].isalnum() or text[pos] == '-'):
        indexes.work.scan()
        pos += 1
    while pos < end:
        indexes.work.scan()
        spaced = text[pos].isspace()
        pos = indexes.nonspace[pos]
        if text[pos:pos + 2] == '/>':
            return pos + 2
        if text[pos:pos + 1] == '>':
            return pos + 1
        if pos == end or not spaced or not (
                text[pos].isascii() and (text[pos].isalpha() or text[pos] in '_:')):
            return -1
        while pos < end and text[pos].isascii() and (
                text[pos].isalnum() or text[pos] in '_.:-'):
            indexes.work.scan()
            pos += 1
        after_name = pos
        pos = indexes.nonspace[pos]
        if text[pos:pos + 1] != '=':
            pos = after_name
            continue
        pos = indexes.nonspace[pos + 1]
        if pos == end:
            return -1
        if text[pos] in "'\"":
            close = indexes.tag_quotes.get(pos, -1)
            if close == -1:
                return -1
            pos = close + 1
        else:
            value = pos
            while pos < end and not text[pos].isspace() and text[pos] not in '"\'=<>`':
                indexes.work.scan()
                pos += 1
            if value == pos:
                return -1
    return -1
