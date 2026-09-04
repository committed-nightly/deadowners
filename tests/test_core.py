from __future__ import annotations

from deadowners.codeowners import parse
from deadowners.core import (
    BAD_PATTERN,
    IGNORED_FILE,
    POINTLESS_UNOWNING,
    SHADOWED,
    UNMATCHED,
    check,
    owner_of,
)

FILES = [
    "README.md",
    "docs/index.md",
    "docs/guides/setup.md",
    "src/api/main.py",
    "src/web/app.tsx",
    "services/billing/pay.go",
    "infra/main.tf",
]


def run(text: str, paths=None, ignored=()):
    return check(parse(text, "CODEOWNERS"), list(FILES if paths is None else paths), ignored)


def kinds(report):
    return [(f.kind, f.line) for f in report.findings]


def test_a_healthy_file_has_nothing_dead():
    report = run("*  @eng\ndocs/  @writers\nsrc/api/  @api\n")
    assert report.ok
    assert report.live_rules == 3
    assert report.files_checked == len(FILES)


def test_a_pattern_matching_nothing_is_unmatched():
    report = run("*  @eng\npackages/widgets/  @widgets\n")
    assert kinds(report) == [(UNMATCHED, 2)]


def test_a_rule_a_later_rule_takes_everything_from_is_shadowed():
    report = run("*  @eng\n*.tf  @infra\ninfra/  @platform\n")
    assert kinds(report) == [(SHADOWED, 2)]
    finding = report.findings[0]
    assert finding.matched == 1
    assert [t.rule.line for t in finding.taken_by] == [3]
    assert finding.taken_by[0].samples == ("infra/main.tf",)


def test_shadowing_is_reported_even_when_no_single_later_rule_covers_it():
    """The case pattern-algebra checkers miss.

    `docs/` is not a subset of either later rule on its own. It is dead all
    the same, because between them they take every file it has.
    """
    report = run(
        "*  @eng\n"
        "docs/  @writers\n"
        "docs/index.md  @a\n"
        "docs/guides/  @b\n"
    )
    assert kinds(report) == [(SHADOWED, 2)]
    assert [t.rule.line for t in report.findings[0].taken_by] == [3, 4]


def test_a_rule_keeping_even_one_file_is_alive():
    report = run("*  @eng\ndocs/  @writers\ndocs/index.md  @a\n")
    assert report.ok


def test_a_duplicated_pattern_shadows_its_own_earlier_copy():
    report = run("*  @eng\nsrc/  @old\nsrc/  @new\n")
    assert kinds(report) == [(SHADOWED, 2)]


def test_an_ownerless_rule_that_strips_a_real_owner_is_alive():
    report = run("*  @eng\nservices/billing/\n")
    assert report.ok


def test_an_ownerless_rule_with_nothing_above_it_is_pointless():
    """It removes an owner that was never assigned."""
    report = run("docs/  @writers\nservices/billing/\n")
    assert kinds(report) == [(POINTLESS_UNOWNING, 2)]
    assert report.findings[0].samples == ("services/billing/pay.go",)


def test_an_ownerless_rule_is_only_pointless_when_it_strips_nothing_at_all():
    """Half of its files had an owner, so the line does something."""
    report = run("docs/  @writers\ndocs/index.md\nREADME.md\n")
    # line 2 strips @writers from docs/index.md -- real work.
    # line 3 strips nothing, because no earlier rule matches README.md.
    assert kinds(report) == [(POINTLESS_UNOWNING, 3)]


def test_an_ownerless_rule_that_matches_nothing_is_unmatched_not_pointless():
    report = run("*  @eng\nnope/\n")
    assert kinds(report) == [(UNMATCHED, 2)]


def test_bad_patterns_are_reported_against_their_line():
    report = run("*  @eng\n[a-z].py  @x\n")
    assert kinds(report) == [(BAD_PATTERN, 2)]
    assert "character range" in report.findings[0].reason


def test_a_second_codeowners_file_is_dead_in_its_entirety():
    other = parse("*  @nobody\nsrc/  @nobody\n", "CODEOWNERS")
    report = run("*  @eng\n", ignored=(other,))
    assert kinds(report) == [(IGNORED_FILE, 0)]
    assert report.findings[0].matched == 2
    assert report.findings[0].file == "CODEOWNERS"


def test_bad_lines_in_an_ignored_file_are_still_reported():
    other = parse("!x  @nobody\n", "docs/CODEOWNERS")
    report = run("*  @eng\n", ignored=(other,))
    assert {f.kind for f in report.findings} == {IGNORED_FILE, BAD_PATTERN}


def test_findings_come_out_in_file_then_line_order():
    """The file GitHub reads first, in line order; the dead files after it."""
    other = parse("*  @nobody\n", "docs/CODEOWNERS")
    report = run("*  @eng\nz/  @z\n[a].py  @a\nq/  @q\n", ignored=(other,))
    assert [(f.file, f.line) for f in report.findings] == [
        ("CODEOWNERS", 2),
        ("CODEOWNERS", 3),
        ("CODEOWNERS", 4),
        ("docs/CODEOWNERS", 0),
    ]


def test_the_read_file_still_comes_first_when_both_files_share_a_name():
    """`.github/CODEOWNERS` and `CODEOWNERS` have the same basename.

    Ordering on the name rather than on which file GitHub reads would put
    the dead one at the top of the report.
    """
    other = parse("!x  @nobody\n", "CODEOWNERS")
    report = check(parse("z/  @z\n", ".github/CODEOWNERS"), list(FILES), (other,))
    assert [(f.file, f.kind) for f in report.findings] == [
        (".github/CODEOWNERS", UNMATCHED),
        ("CODEOWNERS", IGNORED_FILE),
        ("CODEOWNERS", BAD_PATTERN),
    ]


def test_an_empty_file_has_no_findings():
    report = run("# nothing but a comment\n")
    assert report.ok
    assert report.rules_checked == 0


def test_a_repository_with_no_files_makes_every_rule_unmatched():
    report = run("*  @eng\ndocs/  @writers\n", paths=[])
    assert kinds(report) == [(UNMATCHED, 1), (UNMATCHED, 2)]


def test_owner_of_is_the_last_matching_rule():
    parsed = parse("*  @eng\ndocs/  @writers\ndocs/index.md  @a\n", "CODEOWNERS")
    assert owner_of(parsed.rules, "docs/index.md").owners == ("@a",)
    assert owner_of(parsed.rules, "docs/guides/setup.md").owners == ("@writers",)
    assert owner_of(parsed.rules, "src/api/main.py").owners == ("@eng",)


def test_owner_of_is_none_when_nothing_matches():
    parsed = parse("docs/  @writers\n", "CODEOWNERS")
    assert owner_of(parsed.rules, "src/api/main.py") is None
