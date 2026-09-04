"""CODEOWNERS pattern matching.

This is the whole tool. Every finding deadowners reports is a claim about
which rule matches which file, so if this module is wrong the tool is worse
than useless -- it tells you to delete a line that was doing work.

CODEOWNERS patterns are *nearly* gitignore patterns, and the difference is the
thing that catches every implementation out. gitignore matches directories,
and anything under a matched directory is matched too. So to git,
``docs/*`` matches ``docs/build-app/`` and therefore matches
``docs/build-app/troubleshooting.md``. GitHub's docs say the opposite in as
many words: ``docs/*`` matches ``docs/getting-started.md`` "but not further
nested files". You cannot use ``git check-ignore`` as an oracle here.

But GitHub's docs also say ``**/logs`` owns "any file in a ``/logs``
directory such as ``/build/logs``" -- which *is* recursion into a matched
directory. Both statements are in the same document.

The single rule that reproduces every example GitHub publishes:

    a pattern also matches everything underneath it, unless its last
    segment contains a wildcard.

Walk the published examples:

===================  ==========  =================================
pattern              recurses?   why
===================  ==========  =================================
``docs/*``           no          last segment ``*`` is a wildcard
``docs/*.md``        no          last segment ``*.md`` is a wildcard
``*.js``             no          last segment ``*.js`` is a wildcard
``apps/``            yes         trailing slash, no last segment
``/build/logs/``     yes         trailing slash
``**/logs``          yes         last segment ``logs`` is literal
``/apps/github``     yes         last segment ``github`` is literal
===================  ==========  =================================

That rule is inferred, not documented. GitHub has never published the
matcher and the implementations in the wild disagree about exactly this
case -- see mszostok/codeowners-validator#169 and beaugunderson/codeowners#15,
which are both bug reports about ``foo/*``. Every row above is pinned by a
test, so if GitHub is ever pinned down properly the disagreement will show up
as a failing table entry rather than as quietly wrong output.

Everything else follows gitignore, and the gitignore-derived parts *are*
checked against real ``git check-ignore`` in the test suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class PatternError(ValueError):
    """A pattern GitHub will not do anything useful with."""


# gitignore supports these; CODEOWNERS explicitly does not. GitHub's docs list
# all three by name under "syntax exceptions".
UNSUPPORTED = {
    "!": "`!` negation is not supported in CODEOWNERS (it is in .gitignore)",
    "[": "`[ ]` character ranges are not supported in CODEOWNERS",
    "\\": "`\\` escaping is not supported in CODEOWNERS",
}


def _segment_has_wildcard(segment: str) -> bool:
    return any(c in segment for c in "*?")


def _translate_segment(segment: str) -> str:
    """One path segment of a glob, as a regex that cannot cross a ``/``."""
    out = []
    for char in segment:
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
    return "".join(out)


@dataclass(frozen=True)
class Pattern:
    """A compiled CODEOWNERS path pattern."""

    source: str
    _regex: re.Pattern[str]
    anchored: bool
    recursive: bool

    def matches(self, path: str) -> bool:
        """Does this pattern own ``path``? ``path`` is repo-root-relative."""
        return self._regex.match(path) is not None

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.source


def compile_pattern(source: str) -> Pattern:
    """Compile one CODEOWNERS pattern, or raise PatternError."""
    if not source:
        raise PatternError("empty pattern")

    if source.startswith("!"):
        raise PatternError(UNSUPPORTED["!"])
    for char in ("[", "\\"):
        if char in source:
            raise PatternError(UNSUPPORTED[char])

    body = source
    trailing_slash = body.endswith("/")
    if trailing_slash:
        body = body[:-1]

    # A leading slash anchors to the repository root and is not part of the
    # path. A pattern containing a slash anywhere else is anchored too --
    # this is gitignore's rule, and the reason `docs/a.md` does not match
    # `src/docs/a.md` while a bare `a.md` matches at any depth. A *trailing*
    # slash does not count as a separator for this test, so `apps/` is
    # unanchored and matches an apps directory at any depth.
    if body.startswith("/"):
        body = body[1:]
        anchored = True
    else:
        anchored = "/" in body

    # `a/**` means "everything inside a", which is what the recursive suffix
    # already does. Folding it away here keeps the segment translator from
    # having to special-case a `**` with nothing after it.
    trailing_globstar = False
    segments = body.split("/") if body else []
    while segments and segments[-1] == "**":
        segments.pop()
        trailing_globstar = True

    if not segments:
        if trailing_slash or trailing_globstar:
            # `/`, `**`, `/**` -- the whole repository. Nobody writes these on
            # purpose, but they are not errors and they do own everything.
            return Pattern(
                source=source,
                _regex=re.compile(r"^.*$"),
                anchored=True,
                recursive=True,
            )
        raise PatternError("empty pattern")

    body = "/".join(segments)
    parts: list[str] = []
    for i, segment in enumerate(segments):
        if segment == "**":
            # `**` swallows any number of segments, including none. The
            # trailing `/` is folded in so that `a/**/b` matches `a/b`.
            parts.append("(?:[^/]+/)*")
        else:
            parts.append(_translate_segment(segment))
            if i < len(segments) - 1:
                parts.append("/")

    prefix = "" if anchored else "(?:.*/)?"
    # The inferred rule, and the one thing in this file that is not gitignore:
    # a pattern reaches into subdirectories unless its last segment is a glob.
    recursive = (
        trailing_slash
        or trailing_globstar
        or not _segment_has_wildcard(segments[-1])
    )
    suffix = "(?:/.*)?" if recursive else ""

    regex = re.compile(f"^{prefix}{''.join(parts)}{suffix}$")
    return Pattern(source=source, _regex=regex, anchored=anchored, recursive=recursive)
