"""CommonMark bracket-stack inlines with indexed, non-rescanning lookahead."""
from dataclasses import dataclass
from html import unescape
from html.entities import html5
import re
from string import punctuation
import unicodedata

from report_title_emphasis import Delimiter, Emphasis, Text
from report_title_render import render_title
from report_title_scan import AUTOLINK, destination_end, html_tag_end, indexes_for
from report_title_work import ParseWork

ENTITY = re.compile(r'&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});')


def label_key(label: str) -> str:
    """CommonMark reference labels: whitespace-folded Unicode case folding."""
    return ' '.join(label.split()).casefold()


@dataclass(slots=True)
class Bracket:
    """Accumulator for one unmatched bracket and its delimiter-stack boundary."""

    position: int
    token: int
    image: bool
    bottom: Delimiter | None
    nested: bool = False


def _flanks(text: str, span: tuple[int, int]) -> tuple[bool, bool]:
    start, end = span
    before = text[start - 1:start] if start else ''
    after = text[end:end + 1]
    before_space, after_space = not before or before.isspace(), not after or after.isspace()
    before_punct = bool(before) and (before in punctuation or unicodedata.category(before)[0] in 'PS')
    after_punct = bool(after) and (after in punctuation or unicodedata.category(after)[0] in 'PS')
    left = not after_space and (not after_punct or before_space or before_punct)
    right = not before_space and (not before_punct or after_space or after_punct)
    if text[start] == '_':
        return left and (not right or before_punct), right and (not left or after_punct)
    # Existing report contract treats inter-digit multiplication as literal.
    if text[start] == '*' and before.isdigit() and after.isdigit():
        return False, False
    return left, right


def inline_text(text: str, references: set[str], table: bool = False,
                work: ParseWork | None = None) -> tuple[str, bool, bool]:
    """Resolve the entire line before bounded emission; optional meter is a test seam."""
    meter = work if work is not None else ParseWork()
    indexes = indexes_for(text, meter)
    tokens: list[Text] = []
    brackets: list[Bracket] = []
    emphasis = Emphasis(meter)
    inactive_before = -1
    pos = 0
    while pos < len(text):
        meter.tokens += 1
        meter.scan()
        char = text[pos]
        if char == '\\' and text[pos + 1:pos + 2] in punctuation and pos + 1 < len(text):
            tokens.append(Text(text[pos + 1], True))
            pos += 2
            continue
        if char == '`':
            end = pos + 1
            while end < len(text) and text[end] == '`':
                meter.scan()
                end += 1
            close = indexes.code.get(pos, -1)
            if close != -1:
                meter.scan(close - end)
                value = text[end:close].replace('\n', ' ')
                if value.startswith(' ') and value.endswith(' ') and value.strip(' '):
                    meter.scan(2 * len(value))
                    value = value[1:-1]
                tokens.append(Text(value, True))
                pos = close + end - pos
                continue
            tokens.append(Text(text[pos:end]))
            pos = end
            continue
        if char == '[' or text.startswith('![', pos):
            image = char == '!'
            if brackets:
                brackets[-1].nested = True
            brackets.append(Bracket(pos + int(image), len(tokens), image, emphasis.tail))
            tokens.append(Text('![' if image else '['))
            pos += 1 + int(image)
            continue
        if char == ']' and brackets:
            bracket = brackets.pop()  # Failed and successful lookups both remove their opener.
            end = -1
            key = ''
            if bracket.image or bracket.position >= inactive_before:
                if text[pos + 1:pos + 2] == '(':
                    end = destination_end(text, pos + 1, indexes)
                if end == -1:
                    label_start = pos + 2
                    label_end = indexes.square[label_start] if text[pos + 1:pos + 2] == '[' else len(text)
                    full = label_end < len(text) and indexes.opening[label_start] >= label_end
                    if full and 0 < label_end - label_start <= 999:
                        meter.scan(label_end - label_start)
                        key = label_key(text[label_start:label_end])
                    elif ((not full or label_end == label_start) and not bracket.nested
                          and pos - bracket.position <= 1000):
                        meter.scan(pos - bracket.position - 1)
                        key = label_key(text[bracket.position + 1:pos])
                    if key in references and (full or text[pos + 1:pos + 2] != '['):
                        end = label_end + 1 if full else pos + 1
            if end != -1:
                emphasis.process(bracket.bottom)
                tokens[bracket.token].hidden = True
                if key.startswith('^') and not bracket.image:
                    for token in tokens[bracket.token + 1:]:
                        meter.tokens += 1
                        token.hidden = True
                if not bracket.image:
                    inactive_before = bracket.position
                pos = end
                continue
        if char == '<':
            # Autolinks cannot contain '<'. These disjoint windows never rescan
            # one suffix for every potential opener.
            angle_stop = indexes.angle_open[pos + 1]
            meter.scan(angle_stop - pos)
            match = AUTOLINK.match(text, pos, angle_stop)
            if match is not None:
                tokens.append(Text(match.group()[1:-1], True))
                pos = match.end()
                continue
            tag_stop = html_tag_end(text, pos, indexes)
            if tag_stop != -1:
                pos = tag_stop
                continue
            if text.startswith('<!--', pos):
                close = indexes.comments[min(pos + 4, len(text))]
                if close < len(text):
                    pos = close + 3
                    continue
        if char == '&':
            match = ENTITY.match(text, pos)
            meter.scan(min(34, len(text) - pos))
            if match is not None:
                entity = match.group()
                decoded = unescape(entity) if entity[1] == '#' else html5.get(entity[1:])
                if decoded is not None:
                    tokens.append(Text(decoded, True))
                    pos = match.end()
                    continue
        if char in '*_~':
            end = pos + 1
            while end < len(text) and text[end] == char:
                meter.scan()
                end += 1
            token = Text(text[pos:end])
            tokens.append(token)
            if char != '~' or end - pos <= 2:
                emphasis.push(token, _flanks(text, (pos, end)))
            pos = end
            continue
        tokens.append(Text(' ' if table and char == '|' else char))
        pos += 1
    emphasis.process()
    return render_title(tokens, meter)
