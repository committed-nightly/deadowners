"""Command line entry point.

Exit codes, because the main use for this is a CI gate:

    0  every rule in CODEOWNERS owns at least one file
    1  at least one rule does nothing
    2  the check could not run at all

2 is deliberately not 1 and very deliberately not 0. No repository, no
CODEOWNERS file, a --ref that doesn't resolve: all of those mean nobody
looked, and "nobody looked" reported as a green tick is worse than no check.

A CODEOWNERS file that exists and contains no rules is a **pass**. There is
nothing in it that can be dead. A CODEOWNERS file that is *missing* is a 2 --
you have pointed a CODEOWNERS checker at a repository that has no CODEOWNERS,
and the most likely reason is that you are running it from the wrong place.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import codeowners, gitcmd
from .codeowners import SEARCH_PATH, ParsedFile
from .core import (
    BAD_PATTERN,
    IGNORED_FILE,
    POINTLESS_UNOWNING,
    SHADOWED,
    UNMATCHED,
    Report,
    check,
)
from .gitcmd import GitError

EXIT_OK = 0
EXIT_DEAD = 1
EXIT_ERROR = 2

HEADLINE = {
    UNMATCHED: "matches no file in the repository",
    SHADOWED: "matches {matched} file{s}, but owns none",
    POINTLESS_UNOWNING: "removes an owner that was never assigned",
    BAD_PATTERN: "GitHub skips this line entirely",
    IGNORED_FILE: "GitHub never reads this file",
}

DETAIL = {
    UNMATCHED: [
        "Nothing here matches it, so it has never requested a review from",
        "anyone. Usually the path moved and the rule didn't; sometimes the",
        "rule is `dir/*` where `dir/` was meant, which stops at the first",
        "level and misses everything nested underneath.",
    ],
    SHADOWED: [
        "CODEOWNERS is last-match-wins, so a later line has taken every file",
        "this one covers. The owners named here are never asked for a review",
        "of anything. Moving the rule below the ones listed would give it",
        "back its files -- if that is what you meant.",
    ],
    POINTLESS_UNOWNING: [
        "A rule with no owners strips ownership, which only does something",
        "when an earlier rule assigned some. No earlier rule matches these",
        "files, so they had no owner before this line and no owner after it.",
    ],
    BAD_PATTERN: [
        "CODEOWNERS does not have all of gitignore's syntax. GitHub does not",
        "reject the file over it -- the line is skipped and everything it was",
        "meant to own falls through to whatever else matches.",
    ],
    IGNORED_FILE: [
        "GitHub looks in .github/, then the root, then docs/, and stops at",
        "the first CODEOWNERS it finds. The others are not merged and not",
        "warned about. Every rule in this one is dead, however good it is.",
    ],
}


def _plural(count: int) -> str:
    return "" if count == 1 else "s"


def _normalise(path: str) -> str:
    """A user-typed path as a repo-relative one.

    Deliberately not ``lstrip("./")``: that strips *characters*, so it turns
    ``.github/CODEOWNERS`` into ``github/CODEOWNERS`` and then matches
    nothing. Dropping one leading ``./`` and any leading ``/`` is all that is
    wanted, since people paste both.
    """
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _print_finding(finding, out) -> None:
    headline = HEADLINE[finding.kind].format(
        matched=finding.matched, s=_plural(finding.matched)
    )

    if finding.kind == IGNORED_FILE:
        print(f"  {finding.file}", file=out)
        print(
            f"      {headline} "
            f"({finding.matched} rule{_plural(finding.matched)} in it)",
            file=out,
        )
    else:
        print(f"  line {finding.line}:  {finding.text}", file=out)
        print(f"      {headline}", file=out)

    if finding.kind == BAD_PATTERN:
        print(f"      {finding.reason}", file=out)

    if finding.taken_by:
        print("      taken by:", file=out)
        for thief in finding.taken_by:
            print(
                f"        line {thief.rule.line}:  {thief.rule.text}"
                f"   ({thief.count} file{_plural(thief.count)})",
                file=out,
            )
            for sample in thief.samples:
                print(f"          {sample}", file=out)
    elif finding.samples:
        for sample in finding.samples:
            print(f"        {sample}", file=out)
        if finding.matched > len(finding.samples):
            more = finding.matched - len(finding.samples)
            print(f"        ... and {more} more", file=out)

    for line in DETAIL[finding.kind]:
        print(f"      {line}", file=out)
    print(file=out)


def print_report(report: Report, out) -> None:
    if report.ok:
        print(
            f"{report.codeowners}: {report.rules_checked} "
            f"rule{_plural(report.rules_checked)}, "
            f"{report.files_checked} file{_plural(report.files_checked)} checked, "
            f"nothing dead",
            file=out,
        )
        return

    print(f"{report.codeowners}", file=out)
    print(file=out)
    for finding in report.findings:
        _print_finding(finding, out)

    dead = len(report.findings)
    print(
        f"{report.rules_checked} rule{_plural(report.rules_checked)} checked "
        f"against {report.files_checked} file{_plural(report.files_checked)}, "
        f"{dead} finding{_plural(dead)}",
        file=out,
    )


def report_to_dict(report: Report) -> dict:
    return {
        "codeowners": report.codeowners,
        "files_checked": report.files_checked,
        "rules_checked": report.rules_checked,
        "live_rules": report.live_rules,
        "findings": [
            {
                "kind": f.kind,
                "file": f.file,
                "line": f.line,
                "text": f.text,
                "pattern": f.pattern,
                "matched": f.matched,
                "reason": f.reason,
                "samples": list(f.samples),
                "taken_by": [
                    {
                        "line": t.rule.line,
                        "text": t.rule.text,
                        "count": t.count,
                        "samples": list(t.samples),
                    }
                    for t in f.taken_by
                ],
            }
            for f in report.findings
        ],
    }


def _load(root: str, ref: str | None, chosen: str | None):
    """Return (winner, ignored_files). Raises GitError or FileNotFoundError."""
    if chosen is not None:
        if ref is None:
            if not os.path.isfile(os.path.join(root, chosen)):
                raise FileNotFoundError(chosen)
            return codeowners.read(root, chosen), ()
        text = gitcmd.show(ref, chosen, root)
        if text is None:
            raise FileNotFoundError(chosen)
        return codeowners.parse(text, chosen), ()

    if ref is None:
        found = codeowners.find_files(root)
        loaded = [codeowners.read(root, rel) for rel in found]
    else:
        loaded = []
        for rel in SEARCH_PATH:
            text = gitcmd.show(ref, rel, root)
            if text is not None:
                loaded.append(codeowners.parse(text, rel))

    if not loaded:
        raise FileNotFoundError(None)
    return loaded[0], tuple(loaded[1:])


def _explain(parsed: ParsedFile, paths: list[str], target: str, out) -> int:
    """Who owns one path, and every rule that had a claim on it."""
    hits = [rule for rule in parsed.rules if rule.matches(target)]
    known = target in set(paths)

    print(f"{target}", file=out)
    if not known:
        print(
            "  (not a file git knows about at this revision -- "
            "matching it anyway)",
            file=out,
        )
    print(file=out)

    if not hits:
        print("  no rule matches it: this file has no code owner", file=out)
        return EXIT_OK

    for rule in hits[:-1]:
        print(f"  line {rule.line}:  {rule.text}", file=out)
        print("      matches, but is overruled below", file=out)
    winner = hits[-1]
    print(f"  line {winner.line}:  {winner.text}", file=out)
    owners = " ".join(winner.owners) if winner.owners else "(nobody -- no owners listed)"
    print(f"      wins.  owner: {owners}", file=out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deadowners",
        description=(
            "Find the lines in your CODEOWNERS that do nothing: patterns that "
            "match no file, and rules a later rule has taken every file from."
        ),
    )
    parser.add_argument(
        "-C",
        dest="cwd",
        default=".",
        metavar="DIR",
        help="run as if started in DIR (default: the current directory)",
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        help=(
            "check this CODEOWNERS instead of searching .github/, the root "
            "and docs/ in GitHub's order"
        ),
    )
    parser.add_argument(
        "--ref",
        metavar="REV",
        help="check the tree at REV instead of the index (default: the index)",
    )
    parser.add_argument(
        "--explain",
        metavar="PATH",
        help="show every rule matching PATH and which one wins, then exit",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out, err = sys.stdout, sys.stderr

    try:
        root = gitcmd.repo_root(args.cwd)
    except GitError as exc:
        print(f"deadowners: {exc}", file=err)
        return EXIT_ERROR
    except FileNotFoundError:
        print(f"deadowners: no such directory: {args.cwd}", file=err)
        return EXIT_ERROR

    ref = None
    if args.ref is not None:
        try:
            ref = gitcmd.resolve(args.ref, root)
        except GitError as exc:
            print(f"deadowners: {exc}", file=err)
            return EXIT_ERROR

    try:
        winner, ignored = _load(root, ref, args.file)
    except FileNotFoundError as exc:
        wanted = exc.args[0] if exc.args else None
        where = f" at {args.ref}" if args.ref else ""
        if wanted:
            print(f"deadowners: no such file{where}: {wanted}", file=err)
        else:
            print(
                f"deadowners: no CODEOWNERS file{where}. Looked in "
                + ", ".join(SEARCH_PATH),
                file=err,
            )
        return EXIT_ERROR
    except OSError as exc:
        print(f"deadowners: cannot read CODEOWNERS: {exc}", file=err)
        return EXIT_ERROR
    except GitError as exc:
        print(f"deadowners: {exc}", file=err)
        return EXIT_ERROR

    try:
        paths = gitcmd.tracked_files(root, ref)
    except GitError as exc:
        print(f"deadowners: {exc}", file=err)
        return EXIT_ERROR

    if args.explain is not None:
        return _explain(winner, paths, _normalise(args.explain), out)

    report = check(winner, paths, ignored)

    if args.json:
        json.dump(report_to_dict(report), out, indent=2)
        print(file=out)
    else:
        print_report(report, out)

    return EXIT_OK if report.ok else EXIT_DEAD


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
