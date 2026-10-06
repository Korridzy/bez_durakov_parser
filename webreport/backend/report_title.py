"""Title extraction with question fallback rather than damaged Markdown slices.

If a safety net cuts a syntax-bearing chosen line, return the question. Plain
text and literal code-block content use bounded direct emission, without parsing
a truncated Markdown slice. No visible line within the document net also falls back.
"""
import re
from collections.abc import Iterator
from typing import Final

from report_title_inline import inline_text, label_key
from report_title_scan import BACKTICKS, html_tag_end, indexes_for
from report_title_render import short_title
from report_title_work import ParseWork

ANSWER_LIMIT: Final = 1000000
INLINE_LIMIT: Final = 200000
TITLE_LIMIT: Final = 120
LINE = re.compile(r'[^\r\n\v\f\x1c-\x1e\x85\u2028\u2029]*(?:\r\n|[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]|$)')
LINE_ENDS = '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029'
BLOCK_TAGS = frozenset((
    'address article aside base basefont blockquote body caption center col colgroup ' +
    'dd details dialog dir div dl dt fieldset figcaption figure footer form frame frameset ' +
    'h1 h2 h3 h4 h5 h6 head header hr html iframe legend li link main menu menuitem nav ' +
    'noframes ol optgroup option p param search section summary table tbody td tfoot th ' +
    'thead title tr track ul').split())
TAG_START = re.compile(r'</?([A-Za-z][A-Za-z0-9-]*)(?=[ \t/>]|$)')
RAW_END = re.compile(r'</(?:pre|script|style|textarea)>', re.I)
DEFINITION = re.compile(
    r'^\[((?:\\.|[^\[\]\\]){1,999})\]:[ \t]*' +
    r'(?:<[^<>\n]*>|[^ \t]+)(?:[ \t]+(?:".*"|\'.*\'|\(.*\)))?[ \t]*$')
FOOTNOTE = re.compile(r'^\[(\^[^\[\]]+)\]:[ \t]*\S')


def _block_text(text: str, work: ParseWork) -> tuple[str, bool]:
    """Advance a cursor over container/heading/list markers, slicing once."""
    pos, heading, in_list = 0, False, False
    while pos < len(text):
        work.tokens += 1
        while pos < len(text) and text[pos].isspace():
            work.scan()
            pos += 1
        if pos == len(text):
            break
        start = pos
        if text[pos] == '>':
            work.scan()
            pos += 1
            continue
        if text[pos] == '#':
            while pos < len(text) and text[pos] == '#':
                work.scan()
                pos += 1
            if pos - start <= 6 and (pos == len(text) or text[pos].isspace()):
                heading = True
                continue
            pos = start
        if text[pos] in '-+*' and (pos + 1 == len(text) or text[pos + 1].isspace()):
            pos += 1
            in_list = True
            continue
        end = pos
        while end < len(text) and text[end].isdigit():
            work.scan()
            end += 1
        if (0 < end - pos <= 9 and end + 1 < len(text)
                and text[end] in '.)' and text[end + 1].isspace()):
            pos = end + 1
            in_list = True
            continue
        break
    if in_list and text[pos:pos + 3] in ('[x]', '[X]', '[ ]'):
        if pos + 3 == len(text) or text[pos + 3].isspace():
            pos += 3
    result = text[pos:].strip()
    work.scan(len(text) - pos)
    if heading:
        tail = result.rstrip('#')
        if tail != result and tail and tail[-1].isspace():
            result = tail.rstrip()
    return result, heading


def _scaffolding(text: str, work: ParseWork) -> bool:
    work.scan(4 * len(text))  # split, join and at most two character-set passes.
    compact = ''.join(text.split())
    return (not compact or set(compact) <= set('|:-')
            or (len(compact) >= 3 and len(set(compact)) == 1 and compact[0] in '*_-='))


def _html_block(text: str, paragraph: bool, work: ParseWork) -> int:
    """CommonMark 0.31.2 HTML block start conditions 1 through 7."""
    if text.startswith('<!--'):
        return 2
    if text.startswith('<?'):
        return 3
    if len(text) > 2 and text.startswith('<!') and text[2].isascii() and text[2].isalpha():
        return 4
    if text.startswith('<![CDATA['):
        return 5
    tag = TAG_START.match(text)
    if tag is not None:
        name = tag[1].lower()
        if not text.startswith('</') and name in ('pre', 'script', 'style', 'textarea'):
            return 1
        if name in BLOCK_TAGS:
            # Retain the existing single-line visible HTML-wrapper contract.
            if (not text.startswith('</')
                    and re.search(r'</' + re.escape(name) + r'\s*>', text, re.I)
                    and inline_text(text[:INLINE_LIMIT], set(), work=work)[0]):
                return 0
            return 6
    if not paragraph and text.startswith('<'):
        indexes = indexes_for(text, work)
        if html_tag_end(text, 0, indexes) == len(text):
            return 7
    return 0


def _html_closed(kind: int, text: str) -> bool:
    match kind:
        case 1:
            return RAW_END.search(text) is not None
        case 2:
            return '-->' in text
        case 3:
            return '?>' in text
        case 4:
            return '>' in text
        case 5:
            return ']]>' in text
        case 6 | 7:
            return not text
        case _:
            return False


def _lines(text: str, work: ParseWork) -> Iterator[str]:
    for line in LINE.finditer(text):
        if line.start() == len(text):
            break
        work.scan(line.end() - line.start())
        work.lines += 1
        yield line.group().rstrip(LINE_ENDS)


def _parse_answer(text: str, references: set[str], work: ParseWork) -> Iterator[tuple[str, bool, bool]]:
    """One forward block cursor; never accumulate visible candidates."""
    lines = _lines(text, work)
    pending: str | None = None
    fence, width, html, paragraph = '', 0, 0, False
    footnote_body = False
    while True:
        line = pending if pending is not None else next(lines, None)
        pending = None
        if line is None:
            break
        stripped = line.strip()
        work.scan(len(line))
        if footnote_body:
            if not stripped or line.startswith(('    ', '\t')):
                continue
            footnote_body = False
        if html:
            work.scan(len(stripped))
            if _html_closed(html, stripped):
                html = 0
                paragraph = False
            continue
        if fence:
            end = 0
            while end < len(stripped) and stripped[end] == fence:
                end += 1
            if end >= width and not stripped[end:].strip():
                fence, width = '', 0
                continue
            literal = True
            content = stripped
        else:
            if not stripped:
                paragraph = False
                continue
            content, heading = _block_text(stripped, work)
            if _scaffolding(content, work):
                paragraph = False
                continue
            if content[0] in '`~':
                end = 0
                while end < len(content) and content[end] == content[0]:
                    end += 1
                runs = [run for run in BACKTICKS.finditer(content)] if content[0] == '`' else []
                work.scan(len(content))
                same_line = (any(run.end() - run.start() == end for run in runs[1:])
                             if runs else content.find(content[:end], end) != -1)
                if end >= 3 and not same_line:
                    fence, width, paragraph = content[0], end, False
                    continue
            # Four or more spaces form literal indented code, not HTML.
            work.scan(len(content))
            html = (_html_block(content[:INLINE_LIMIT], paragraph, work)
                    if len(line) - len(line.lstrip(' ')) < 4 else 0)
            if html:
                if _html_closed(html, content):
                    html = 0
                paragraph = False
                continue
            definition = DEFINITION.fullmatch(content)
            footnote = FOOTNOTE.match(content)
            work.scan(2 * len(content))
            if (definition is not None and not paragraph) or footnote is not None:
                label = definition[1] if definition is not None else footnote[1] if footnote else ''
                references.add(label_key(label))
                footnote_body = footnote is not None
                paragraph = False
                continue
            literal = len(line) - len(line.lstrip(' ')) >= 4
            paragraph = not heading and not literal
        if _scaffolding(content, work):
            continue
        table = content.startswith('|') or content.endswith('|')
        if not table and '|' in content:
            pending = next(lines, None)
            table = pending is not None and '|' in pending and _scaffolding(pending, work)
        yield content, literal, table


def derive_report_title(answer: str, question: str, work: ParseWork | None = None) -> str:
    """Complete legitimate lines; safety nets are not the normal parsing policy."""
    meter = work if work is not None else ParseWork()
    # Direct string slicing via its method retains the established AttributeError
    # for None, which is deliberately outside this function's string contract.
    document = answer.__getitem__(slice(ANSWER_LIMIT))
    if len(answer) > ANSWER_LIMIT:
        # Prefer a complete line. A single oversized line uses a codepoint cut.
        boundary = len(document) - 1
        while boundary >= 0 and document[boundary] not in LINE_ENDS:
            meter.scan()
            boundary -= 1
        if boundary >= 0:
            document = document[:boundary + 1]
    references: set[str] = set()
    blocks = _parse_answer(document, references, meter)
    references_ready = False
    while (candidate := next(blocks, None)) is not None:
        text, literal, table = candidate
        if len(text) > INLINE_LIMIT:
            meter.scan(len(text))
            if literal or not any(char in '\\`*_~[]<>!#|&' for char in text):
                return short_title(iter(text), meter)
            return short_title(iter(question), meter)
        deferred = not literal and '[' in text and not references_ready
        if deferred:
            # Definitions can follow their use. Only this path scans the tail;
            # selection retains one candidate, not an O(number of lines) list.
            for _ in blocks:
                pass
            references_ready = True
        if literal:
            visible = text.strip('|').replace('|', ' ') if table else text
            title = short_title(iter(visible), meter)
        else:
            title, _, protected = inline_text(text, references, table, meter)
            if not protected and set(''.join(title.split())) <= set('*_`~#'):
                title = ''
        if title:
            return title
        if deferred:
            # A resolved footnote-only candidate has no visible text. Revisit
            # selection once with the completed reference table.
            blocks = _parse_answer(document, references, meter)
    return short_title(iter(question), meter)
