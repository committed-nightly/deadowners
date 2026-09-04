"""End to end, through main(), against real git repositories.

The exit codes get the most attention here. This tool exists to sit in CI,
so the failure that matters is not a wrong message -- it is a 0 printed over
a check that never happened.
"""

from __future__ import annotations

import json
import os

import pytest

from deadowners.cli import EXIT_DEAD, EXIT_ERROR, EXIT_OK, main

SOME_FILES = (
    "README.md",
    "docs/index.md",
    "docs/guides/setup.md",
    "src/api/main.py",
    "infra/main.tf",
)


def run(cwd, *args, capsys=None):
    code = main(["-C", cwd, *args])
    captured = capsys.readouterr() if capsys else None
    return code, captured


@pytest.fixture
def populated(repo):
    repo.add_files(*SOME_FILES)
    return repo


def test_a_clean_file_exits_zero(populated, capsys):
    populated.codeowners("*  @eng\ndocs/  @writers\n")
    populated.commit()
    code, out = run(populated.path, capsys=capsys)
    assert code == EXIT_OK
    assert "nothing dead" in out.out


def test_a_dead_rule_exits_one(populated, capsys):
    populated.codeowners("*  @eng\npackages/gone/  @widgets\n")
    populated.commit()
    code, out = run(populated.path, capsys=capsys)
    assert code == EXIT_DEAD
    assert "packages/gone/" in out.out
    assert "matches no file in the repository" in out.out


def test_a_shadowed_rule_names_the_line_that_took_its_files(populated, capsys):
    populated.codeowners("*  @eng\n*.tf  @infra\ninfra/  @platform\n")
    populated.commit()
    code, out = run(populated.path, capsys=capsys)
    assert code == EXIT_DEAD
    assert "taken by:" in out.out
    assert "line 3:" in out.out
    assert "infra/main.tf" in out.out


def test_an_empty_codeowners_is_a_pass_not_an_error(populated, capsys):
    """Nothing in it can be dead, so there is nothing to report."""
    populated.codeowners("# owners go here one day\n")
    populated.commit()
    code, out = run(populated.path, capsys=capsys)
    assert code == EXIT_OK
    assert "0 rules" in out.out


def test_a_missing_codeowners_is_an_error_not_a_pass(populated, capsys):
    """The one thing this tool must never do is tick a check it didn't run."""
    populated.commit()
    code, out = run(populated.path, capsys=capsys)
    assert code == EXIT_ERROR
    assert "no CODEOWNERS file" in out.err
    assert ".github/CODEOWNERS" in out.err


def test_an_untracked_file_is_not_checked(populated, capsys):
    """The question is what GitHub sees, and GitHub sees the repository."""
    populated.codeowners("*  @eng\nbuild/  @b\n")
    populated.commit()
    populated.write("build/out.o")  # never added
    code, out = run(populated.path, capsys=capsys)
    assert code == EXIT_DEAD
    assert "build/" in out.out


def test_a_second_codeowners_file_is_reported_as_never_read(populated, capsys):
    populated.codeowners("*  @eng\n", where=".github/CODEOWNERS")
    populated.codeowners("src/  @api\n", where="CODEOWNERS")
    populated.commit()
    code, out = run(populated.path, capsys=capsys)
    assert code == EXIT_DEAD
    assert "GitHub never reads this file" in out.out
    assert out.out.index(".github/CODEOWNERS") < out.out.index("never reads")


def test_file_overrides_the_search_order(populated, capsys):
    populated.codeowners("*  @eng\n", where=".github/CODEOWNERS")
    populated.codeowners("gone/  @api\n", where="CODEOWNERS")
    populated.commit()
    code, out = run(populated.path, "--file", "CODEOWNERS", capsys=capsys)
    assert code == EXIT_DEAD
    assert "gone/" in out.out
    # Only the named file; nothing about the one that would have won.
    assert "never reads" not in out.out


def test_a_missing_named_file_is_an_error(populated, capsys):
    populated.codeowners("*  @eng\n")
    populated.commit()
    code, out = run(populated.path, "--file", "nope/CODEOWNERS", capsys=capsys)
    assert code == EXIT_ERROR
    assert "no such file" in out.err


def test_not_a_repository_is_an_error(tmp_path, capsys):
    plain = str(tmp_path / "plain")
    os.makedirs(plain)
    code, out = run(plain, capsys=capsys)
    assert code == EXIT_ERROR
    assert "not a git repository" in out.err


def test_a_directory_that_does_not_exist_is_an_error(tmp_path, capsys):
    code, out = run(str(tmp_path / "nope"), capsys=capsys)
    assert code == EXIT_ERROR
    assert out.err.strip()


def test_an_unknown_ref_is_an_error_naming_the_ref(populated, capsys):
    populated.codeowners("*  @eng\n")
    populated.commit()
    code, out = run(populated.path, "--ref", "no-such-branch", capsys=capsys)
    assert code == EXIT_ERROR
    assert "no such revision: no-such-branch" in out.err
    # Not the failed command line, which is what --quiet leaves behind.
    assert "rev-parse" not in out.err


def test_ref_checks_the_tree_at_that_revision(populated, capsys):
    populated.codeowners("*  @eng\ndocs/  @writers\n")
    first = populated.commit()
    populated.codeowners("*  @eng\npackages/gone/  @widgets\n")
    populated.commit()

    code, _ = run(populated.path, "--ref", first, capsys=capsys)
    assert code == EXIT_OK
    code, out = run(populated.path, "--ref", "HEAD", capsys=capsys)
    assert code == EXIT_DEAD
    assert "packages/gone/" in out.out


def test_a_codeowners_added_after_the_ref_is_an_error(populated, capsys):
    first = populated.commit()
    populated.codeowners("*  @eng\n")
    populated.commit()
    code, out = run(populated.path, "--ref", first, capsys=capsys)
    assert code == EXIT_ERROR
    assert "no CODEOWNERS file" in out.err


def test_json_carries_the_same_verdict(populated, capsys):
    populated.codeowners("*  @eng\n*.tf  @infra\ninfra/  @platform\ngone/  @g\n")
    populated.commit()
    code, out = run(populated.path, "--json", capsys=capsys)
    assert code == EXIT_DEAD
    data = json.loads(out.out)
    assert data["codeowners"] == ".github/CODEOWNERS"
    assert data["files_checked"] == len(SOME_FILES) + 1  # + CODEOWNERS itself
    assert {f["kind"] for f in data["findings"]} == {"shadowed", "unmatched"}
    shadowed = next(f for f in data["findings"] if f["kind"] == "shadowed")
    assert shadowed["taken_by"][0]["line"] == 3
    assert shadowed["taken_by"][0]["samples"] == ["infra/main.tf"]


def test_json_of_a_clean_file_has_no_findings(populated, capsys):
    populated.codeowners("*  @eng\n")
    populated.commit()
    code, out = run(populated.path, "--json", capsys=capsys)
    assert code == EXIT_OK
    assert json.loads(out.out)["findings"] == []


def test_explain_shows_the_winner_and_everything_it_beat(populated, capsys):
    populated.codeowners("*  @eng\ndocs/  @writers\ndocs/index.md  @a\n")
    populated.commit()
    code, out = run(populated.path, "--explain", "docs/index.md", capsys=capsys)
    assert code == EXIT_OK
    assert "overruled below" in out.out
    assert "wins.  owner: @a" in out.out


def test_explain_reports_an_unowned_path(populated, capsys):
    populated.codeowners("docs/  @writers\n")
    populated.commit()
    code, out = run(populated.path, "--explain", "src/api/main.py", capsys=capsys)
    assert code == EXIT_OK
    assert "no code owner" in out.out


def test_explain_says_when_the_path_is_not_in_the_repository(populated, capsys):
    populated.codeowners("*  @eng\n")
    populated.commit()
    code, out = run(populated.path, "--explain", "not/here.py", capsys=capsys)
    assert code == EXIT_OK
    assert "not a file git knows about" in out.out


@pytest.mark.parametrize(
    "typed", ["./.github/CODEOWNERS", "/.github/CODEOWNERS", ".github/CODEOWNERS"]
)
def test_explain_accepts_a_pasted_path(populated, capsys, typed):
    """`lstrip("./")` would eat the leading dot and match nothing."""
    populated.codeowners("*  @eng\n.github/  @ops\n")
    populated.commit()
    code, out = run(populated.path, "--explain", typed, capsys=capsys)
    assert code == EXIT_OK
    assert "wins.  owner: @ops" in out.out


def test_it_runs_from_a_subdirectory(populated, capsys):
    populated.codeowners("*  @eng\ngone/  @g\n")
    populated.commit()
    code, out = run(os.path.join(populated.path, "src", "api"), capsys=capsys)
    assert code == EXIT_DEAD
    assert "gone/" in out.out
