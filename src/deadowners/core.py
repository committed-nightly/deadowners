"""Working out which rules do nothing.

The method is deliberately dumb: take every file git knows about, run the
whole rule list over it, and see which rule wins. A rule that wins nothing is
dead. There is no pattern algebra here and no attempt to prove one pattern
subsumes another, because the interesting dead rules in real repositories
aren't subsumed by any single later rule -- they're eaten by three later
rules between them, or they point at a directory that was renamed in 2023.

The cost of that choice is that a finding is only ever a statement about
*this* repository at *this* revision: a rule matching nothing today may be
waiting for a file somebody adds tomorrow. The tool says so rather than
pretending otherwise, and every finding carries the evidence -- the files, and
the later rule that took each one -- so a claim can be checked by eye instead
of believed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .codeowners import BadLine, ParsedFile, Rule

#: A rule whose pattern matches no file that exists.
UNMATCHED = "unmatched"
#: A rule that matches files, but a later rule owns every one of them.
SHADOWED = "shadowed"
#: An owner-less rule that removes ownership nothing had in the first place.
POINTLESS_UNOWNING = "pointless-unowning"
#: A CODEOWNERS file GitHub never opens, because an earlier location won.
IGNORED_FILE = "ignored-file"
#: A pattern GitHub cannot use, so the line is skipped wholesale.
BAD_PATTERN = "bad-pattern"

#: How many example paths to keep per finding. Enough to recognise what the
#: rule was aimed at, few enough to read.
SAMPLES = 3


@dataclass(frozen=True)
class Thief:
    """A later rule that took files from an earlier one."""

    rule: Rule
    count: int
    samples: tuple[str, ...]


@dataclass(frozen=True)
class Finding:
    kind: str
    line: int
    text: str
    pattern: str = ""
    matched: int = 0
    reason: str = ""
    taken_by: tuple[Thief, ...] = ()
    samples: tuple[str, ...] = ()
    file: str = ""


@dataclass
class Report:
    codeowners: str
    files_checked: int
    rules_checked: int
    findings: list[Finding] = field(default_factory=list)
    #: Rules that are doing work, kept so the summary can say how many.
    live_rules: int = 0

    @property
    def ok(self) -> bool:
        return not self.findings


def owner_of(rules: tuple[Rule, ...], path: str) -> Rule | None:
    """The rule GitHub would use for ``path``: the last one that matches."""
    for rule in reversed(rules):
        if rule.matches(path):
            return rule
    return None


def check(
    parsed: ParsedFile,
    paths: list[str],
    ignored_files: tuple[ParsedFile, ...] = (),
) -> Report:
    """Find every rule in ``parsed`` that does nothing to ``paths``."""
    rules = parsed.rules
    report = Report(
        codeowners=parsed.path, files_checked=len(paths), rules_checked=len(rules)
    )

    # matched[i]  -- files rule i matches at all
    # won[i]      -- files rule i actually owns, being the last match
    # taken[i][j] -- files rule i matches that later rule j took
    matched: list[list[str]] = [[] for _ in rules]
    won: list[list[str]] = [[] for _ in rules]
    taken: list[dict[int, list[str]]] = [{} for _ in rules]
    # For an owner-less rule: did anything earlier actually own this file?
    unowning_did_work: list[bool] = [False for _ in rules]

    for path in paths:
        hits = [i for i, rule in enumerate(rules) if rule.matches(path)]
        if not hits:
            continue
        winner = hits[-1]
        for i in hits:
            matched[i].append(path)
        won[winner].append(path)
        for i in hits[:-1]:
            taken[i].setdefault(winner, []).append(path)

        if not rules[winner].owners:
            # The winning rule strips ownership. It only did something if an
            # earlier matching rule would have assigned an owner.
            if any(rules[i].owners for i in hits[:-1]):
                unowning_did_work[winner] = True

    for i, rule in enumerate(rules):
        if not matched[i]:
            report.findings.append(
                Finding(
                    kind=UNMATCHED,
                    line=rule.line,
                    text=rule.text,
                    pattern=rule.source,
                    file=parsed.path,
                )
            )
        elif not won[i]:
            thieves = tuple(
                Thief(
                    rule=rules[j],
                    count=len(took),
                    samples=tuple(sorted(took)[:SAMPLES]),
                )
                for j, took in sorted(taken[i].items())
            )
            report.findings.append(
                Finding(
                    kind=SHADOWED,
                    line=rule.line,
                    text=rule.text,
                    pattern=rule.source,
                    matched=len(matched[i]),
                    taken_by=thieves,
                    samples=tuple(sorted(matched[i])[:SAMPLES]),
                    file=parsed.path,
                )
            )
        elif not rule.owners and not unowning_did_work[i]:
            report.findings.append(
                Finding(
                    kind=POINTLESS_UNOWNING,
                    line=rule.line,
                    text=rule.text,
                    pattern=rule.source,
                    matched=len(matched[i]),
                    samples=tuple(sorted(won[i])[:SAMPLES]),
                    file=parsed.path,
                )
            )
        else:
            report.live_rules += 1

    # The file GitHub actually reads comes first, in line order. Sorting the
    # whole list at the end would order by filename instead, which puts the
    # groups in the wrong place as soon as two CODEOWNERS files share a name.
    report.findings.extend(_bad_pattern_findings(parsed.path, parsed.bad_lines))
    report.findings.sort(key=lambda f: f.line)

    for other in ignored_files:
        report.findings.append(
            Finding(
                kind=IGNORED_FILE,
                line=0,
                text=other.path,
                matched=len(other.rules),
                file=other.path,
            )
        )
        report.findings.extend(
            sorted(
                _bad_pattern_findings(other.path, other.bad_lines),
                key=lambda f: f.line,
            )
        )

    return report


def _bad_pattern_findings(path: str, bad_lines: tuple[BadLine, ...]) -> list[Finding]:
    return [
        Finding(
            kind=BAD_PATTERN,
            line=bad.line,
            text=bad.text,
            reason=bad.reason,
            file=path,
        )
        for bad in bad_lines
    ]
