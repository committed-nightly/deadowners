"""Reading a CODEOWNERS file into rules.

The format is one rule per line: a path pattern, then zero or more owners,
``#`` starts a comment, blank lines are ignored. There is no escaping, so a
pattern containing a space cannot be written at all -- splitting on
whitespace is not a shortcut here, it is the format.

Zero owners is legal and load-bearing. GitHub's own documentation uses it to
carve a hole in a broader rule::

    /apps/         @octocat
    /apps/github

Files under ``/apps/github`` end up with no owner at all, which is the point.
So a rule with no owners is not malformed and is not dead -- it does
something, as long as there was ownership there for it to remove.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .pattern import Pattern, PatternError, compile_pattern

#: Where GitHub looks, in the order it looks. The first file found is the
#: only one used; the others are not merged, not warned about, and not
#: consulted again.
SEARCH_PATH = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


@dataclass(frozen=True)
class Rule:
    """One usable line of a CODEOWNERS file."""

    line: int
    text: str  # the line as written, stripped
    pattern: Pattern
    owners: tuple[str, ...]

    @property
    def source(self) -> str:
        return self.pattern.source

    def matches(self, path: str) -> bool:
        return self.pattern.matches(path)


@dataclass(frozen=True)
class BadLine:
    """A line that has a pattern shaped like a rule but GitHub cannot use."""

    line: int
    text: str
    reason: str


@dataclass(frozen=True)
class ParsedFile:
    path: str  # repo-relative
    rules: tuple[Rule, ...]
    bad_lines: tuple[BadLine, ...]


def _strip_comment(line: str) -> str:
    """Everything before the first ``#``.

    CODEOWNERS has no escaping, so there is no such thing as a ``#`` that
    isn't the start of a comment. GitHub's docs say so directly: escaping one
    with a backslash "doesn't work".
    """
    return line.split("#", 1)[0]


def parse(text: str, path: str) -> ParsedFile:
    """Parse CODEOWNERS text into rules, in file order."""
    rules: list[Rule] = []
    bad: list[BadLine] = []

    for number, raw in enumerate(text.splitlines(), start=1):
        content = _strip_comment(raw).strip()
        if not content:
            continue

        fields = content.split()
        pattern_text, owners = fields[0], tuple(fields[1:])
        try:
            compiled = compile_pattern(pattern_text)
        except PatternError as exc:
            bad.append(BadLine(line=number, text=content, reason=str(exc)))
            continue

        rules.append(
            Rule(line=number, text=content, pattern=compiled, owners=owners)
        )

    return ParsedFile(path=path, rules=tuple(rules), bad_lines=tuple(bad))


def find_files(root: str) -> list[str]:
    """Every CODEOWNERS in the repo, in GitHub's search order.

    Returns all of them, not just the winner. A repository with two is a
    repository where one of them does nothing at all, and that is a finding
    rather than a detail.
    """
    return [rel for rel in SEARCH_PATH if os.path.isfile(os.path.join(root, rel))]


def read(root: str, relpath: str) -> ParsedFile:
    full = os.path.join(root, relpath)
    with open(full, "r", encoding="utf-8", errors="replace") as handle:
        return parse(handle.read(), relpath)
