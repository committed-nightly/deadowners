from __future__ import annotations

from deadowners.codeowners import find_files, parse


def test_rules_keep_their_line_numbers():
    parsed = parse("# comment\n\n*.py  @a\n\n/docs/  @b\n", "CODEOWNERS")
    assert [rule.line for rule in parsed.rules] == [3, 5]


def test_owners_are_split_on_whitespace():
    parsed = parse("*.py   @a  @org/team   person@example.com\n", "CODEOWNERS")
    assert parsed.rules[0].owners == ("@a", "@org/team", "person@example.com")


def test_a_rule_may_have_no_owners():
    """Legal, and load-bearing -- it is how you carve a hole in a rule."""
    parsed = parse("/apps/  @a\n/apps/github\n", "CODEOWNERS")
    assert parsed.rules[1].owners == ()
    assert not parsed.bad_lines


def test_trailing_comments_are_stripped():
    parsed = parse("*.py  @a  # the python people\n", "CODEOWNERS")
    assert parsed.rules[0].owners == ("@a",)
    assert parsed.rules[0].text == "*.py  @a"


def test_a_comment_cannot_be_escaped():
    """CODEOWNERS has no escaping, so there is no non-comment `#`."""
    parsed = parse("\\#notacomment  @a\n", "CODEOWNERS")
    assert parsed.rules == ()
    assert len(parsed.bad_lines) == 1


def test_unusable_patterns_become_bad_lines_not_rules():
    parsed = parse("*.py  @a\n[a-z].py  @b\n!x  @c\n", "CODEOWNERS")
    assert len(parsed.rules) == 1
    assert [bad.line for bad in parsed.bad_lines] == [2, 3]
    assert "character range" in parsed.bad_lines[0].reason


def test_a_gitlab_section_header_is_reported_rather_than_silently_dropped():
    parsed = parse("[Documentation]\n*.md  @a\n", "CODEOWNERS")
    assert parsed.bad_lines[0].line == 1


def test_find_files_returns_every_location_in_githubs_order(repo):
    repo.codeowners("*  @a", where="docs/CODEOWNERS")
    repo.codeowners("*  @b", where="CODEOWNERS")
    repo.codeowners("*  @c", where=".github/CODEOWNERS")
    assert find_files(repo.path) == [
        ".github/CODEOWNERS",
        "CODEOWNERS",
        "docs/CODEOWNERS",
    ]


def test_find_files_is_empty_when_there_is_none(repo):
    assert find_files(repo.path) == []
