"""CommonMark delimiter-stack processing; retain text, not rendering nodes.

The linked stack and openers_bottom buckets follow CommonMark 0.31.2's
appendix algorithm. Mutable nodes accumulate delimiter consumption; rendering
slices each text node once, rather than copying a long delimiter run repeatedly.
"""
from dataclasses import dataclass
from report_title_work import ParseWork


@dataclass(slots=True)
class Text:
    """Mutable inline text node: delimiter processing consumes its edges."""

    value: str
    literal: bool = False
    left: int = 0
    right: int = 0
    hidden: bool = False

    def render(self) -> str:
        return '' if self.hidden else self.value[self.left:len(self.value) - self.right]


@dataclass(slots=True, eq=False)
class Delimiter:
    """Linked accumulator; identity matters when a bracket bounds emphasis."""

    token: Text
    marker: str
    length: int
    original: int
    opens: bool
    closes: bool
    order: int
    previous: 'Delimiter | None' = None
    next: 'Delimiter | None' = None


class Emphasis:
    """Own the mutable delimiter list for one inline parse."""

    def __init__(self, work: ParseWork) -> None:
        self.head: Delimiter | None = None
        self.tail: Delimiter | None = None
        self.count: int = 0
        self.work: ParseWork = work

    def push(self, token: Text, flags: tuple[bool, bool]) -> None:
        self.work.delimiters += 1
        node = Delimiter(token, token.value[0], len(token.value), len(token.value),
                         flags[0], flags[1], self.count, self.tail)
        self.count += 1
        if self.tail is None:
            self.head = node
        else:
            self.tail.next = node
        self.tail = node

    def remove(self, node: Delimiter) -> None:
        self.work.delimiters += 1
        if node.previous is None:
            self.head = node.next
        else:
            node.previous.next = node.next
        if node.next is None:
            self.tail = node.previous
        else:
            node.next.previous = node.previous

    def process(self, bottom: Delimiter | None = None) -> None:
        """Consume matching runs, including partial/shared closers and rule 3."""
        floor = bottom.order if bottom is not None else -1
        lower: dict[tuple[str, bool, int], int] = {}
        closer = bottom.next if bottom is not None else self.head
        while closer is not None:
            self.work.delimiters += 1
            following = closer.next
            if not closer.closes:
                closer = following
                continue
            key = (closer.marker, closer.opens, closer.original % 3)
            limit = lower.get(key, floor)
            opener = closer.previous
            while opener is not None and opener.order > limit:
                self.work.delimiters += 1
                odd = (closer.opens or opener.closes) and (
                    (opener.original + closer.original) % 3 == 0
                    and (opener.original % 3 != 0 or closer.original % 3 != 0))
                if (opener.marker == closer.marker and opener.opens
                        and (closer.marker == '~' or not odd)):
                    break
                opener = opener.previous
            if opener is None or opener.order <= limit:
                lower[key] = closer.previous.order if closer.previous is not None else floor
                if not closer.opens:
                    self.remove(closer)
                closer = following
                continue
            used = 2 if opener.length >= 2 and closer.length >= 2 else 1
            opener.length -= used
            closer.length -= used
            opener.token.right += used
            closer.token.left += used
            between = opener.next
            while between is not None and between is not closer:
                self.work.delimiters += 1
                next_between = between.next
                self.remove(between)
                between = next_between
            if opener.length == 0:
                self.remove(opener)
            if closer.length == 0:
                self.remove(closer)
                closer = following
        # A completed bracket's children cannot pair with outside delimiters.
        remaining = bottom.next if bottom is not None else self.head
        while remaining is not None:
            self.work.delimiters += 1
            following = remaining.next
            self.remove(remaining)
            remaining = following
