"""Deterministic work instrumentation shared by the real title scanners."""
from dataclasses import dataclass


@dataclass(slots=True)
class ParseWork:
    """Count examined characters, token dispatches and delimiter-list steps."""

    characters: int = 0
    tokens: int = 0
    delimiters: int = 0
    emitted: int = 0
    lines: int = 0

    @property
    def total(self) -> int:
        return self.characters + self.tokens + self.delimiters

    def scan(self, size: int = 1) -> None:
        self.characters += size
