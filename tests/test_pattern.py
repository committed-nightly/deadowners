"""The matcher is the tool. These are the tests that matter most.

Two kinds here:

* the examples GitHub publishes, asserted directly -- these pin the one rule
  in the matcher that is inferred rather than documented; and
* a cross-check against real ``git check-ignore``, which proves the
  gitignore-derived parts are gitignore, and pins the single place where
  CODEOWNERS deliberately is not.
"""

from __future__ import annotations

import pytest

from deadowners.pattern import PatternError, compile_pattern


def matches(pattern: str, path: str) -> bool:
    return compile_pattern(pattern).matches(path)


# --------------------------------------------------------------------------
# Examples straight out of GitHub's "About code owners" page.
# --------------------------------------------------------------------------

GITHUB_DOC_EXAMPLES = [
    # (pattern, path, owned?)
    # "*  ... matches everything"
    ("*", "README.md", True),
    ("*", "deeply/nested/file.js", True),
    # "*.js ... any JavaScript file anywhere in the repository"
    ("*.js", "app.js", True),
    ("*.js", "src/deep/app.js", True),
    ("*.js", "src/app.ts", False),
    # "/build/logs/ ... the build/logs directory in the root and any of its
    #  subdirectories"
    ("/build/logs/", "build/logs/out.txt", True),
    ("/build/logs/", "build/logs/deep/out.txt", True),
    ("/build/logs/", "src/build/logs/out.txt", False),
    # "docs/* ... docs/getting-started.md but not further nested files"
    ("docs/*", "docs/getting-started.md", True),
    ("docs/*", "docs/build-app/troubleshooting.md", False),
    # "apps/ ... any file in an apps directory anywhere"
    ("apps/", "apps/index.js", True),
    ("apps/", "apps/github/index.js", True),
    ("apps/", "src/apps/index.js", True),
    # "/docs/ ... only the docs directory in the root"
    ("/docs/", "docs/index.md", True),
    ("/docs/", "src/docs/index.md", False),
    # "**/logs ... any file in a /logs directory such as /build/logs"
    ("**/logs", "logs/out.txt", True),
    ("**/logs", "build/logs/out.txt", True),
    ("**/logs", "deeply/nested/logs/out.txt", True),
    # "/apps/github" with empty owners -- the un-owning example, which only
    # works because a bare final segment reaches into the directory.
    ("/apps/github", "apps/github/index.js", True),
    ("/apps/github", "apps/other/index.js", False),
]


@pytest.mark.parametrize("pattern,path,owned", GITHUB_DOC_EXAMPLES)
def test_github_documented_examples(pattern, path, owned):
    assert matches(pattern, path) is owned


def test_the_inferred_rule_is_the_last_segment():
    """`docs/*` stops at one level; `docs/` and `**/logs` do not.

    This is the only behaviour in the matcher that GitHub has not published a
    matcher for. If it is ever shown to be wrong, this is the test that
    should be changed -- and everything else follows from it.
    """
    assert compile_pattern("docs/*").recursive is False
    assert compile_pattern("docs/*.md").recursive is False
    assert compile_pattern("docs/").recursive is True
    assert compile_pattern("**/logs").recursive is True
    assert compile_pattern("/apps/github").recursive is True


# --------------------------------------------------------------------------
# Anchoring, which is pure gitignore.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,path,owned",
    [
        # A slash anywhere but the end anchors to the repository root.
        ("docs/index.md", "docs/index.md", True),
        ("docs/index.md", "src/docs/index.md", False),
        # No slash at all: matches at any depth.
        ("index.md", "index.md", True),
        ("index.md", "src/docs/index.md", True),
        # A trailing slash is not a separator for the purposes of anchoring.
        ("apps/", "a/b/apps/x.js", True),
        ("/apps/", "a/b/apps/x.js", False),
        # `*` does not cross a directory separator.
        ("src/*/main.py", "src/api/main.py", True),
        ("src/*/main.py", "src/api/v2/main.py", False),
        # `**` does.
        ("src/**/main.py", "src/api/v2/main.py", True),
        ("src/**/main.py", "src/main.py", True),
        # `a/**` means everything inside a.
        ("a/**", "a/b/c.txt", True),
        ("a/**", "b/a/c.txt", False),
        # `?` is one character, and not a separator.
        ("src/?.py", "src/a.py", True),
        ("src/?.py", "src/ab.py", False),
        ("src/?.py", "src/a/b.py", False),
    ],
)
def test_anchoring_and_wildcards(pattern, path, owned):
    assert matches(pattern, path) is owned


@pytest.mark.parametrize("pattern", ["/", "**", "/**"])
def test_whole_repository_patterns(pattern):
    assert matches(pattern, "any/old/path.txt") is True


@pytest.mark.parametrize(
    "pattern,reason",
    [
        ("!secret/**", "negation"),
        ("[a-z]*.py", "character range"),
        ("weird\\ name", "escaping"),
        ("", "empty"),
    ],
)
def test_unsupported_syntax_is_an_error(pattern, reason):
    with pytest.raises(PatternError):
        compile_pattern(pattern)


def test_a_bang_only_counts_at_the_start():
    """gitignore only negates with a leading `!`, and so does the check."""
    assert matches("src/oh!.py", "src/oh!.py") is True


def test_dots_and_regex_metacharacters_are_literal():
    assert matches("a.py", "a.py") is True
    assert matches("a.py", "axpy") is False
    assert matches("v1+2/", "v1+2/x.txt") is True
    assert matches("(paren)/", "(paren)/x.txt") is True


# --------------------------------------------------------------------------
# Cross-check against real git.
# --------------------------------------------------------------------------

CROSS_CHECK_PATHS = [
    "README.md",
    "app.js",
    "src/app.js",
    "src/deep/app.js",
    "docs/index.md",
    "docs/guides/setup.md",
    "build/logs/out.txt",
    "build/logs/deep/out.txt",
    "apps/index.js",
    "apps/github/index.js",
    "src/apps/index.js",
    "logs/out.txt",
    "a/b/logs/out.txt",
]

#: Patterns where CODEOWNERS and gitignore should agree exactly: every one
#: whose last segment is a literal, plus the ones with a trailing slash.
AGREES_WITH_GIT = [
    "apps/",
    "/apps/",
    "logs",
    "/logs",
    "**/logs",
    "/build/logs/",
    "docs/index.md",
    "index.md",
    "apps/github",
    "a/**",
    "*",
]

#: The divergence, in full. git recurses into a directory it has matched, so
#: to git `docs/*` matches `docs/guides/` and therefore everything under it.
#: CODEOWNERS does not work that way, and GitHub's docs say so by name.
DIVERGES_FROM_GIT = [
    ("docs/*", "docs/guides/setup.md"),
    ("apps/*", "apps/github/index.js"),
]


@pytest.mark.parametrize("pattern", AGREES_WITH_GIT)
def test_agrees_with_real_git(repo, pattern):
    repo.write(".gitignore", pattern + "\n")
    for path in CROSS_CHECK_PATHS:
        assert matches(pattern, path) == repo.check_ignore(path), (
            f"{pattern!r} vs {path!r}: git says "
            f"{repo.check_ignore(path)}, we say {matches(pattern, path)}"
        )


@pytest.mark.parametrize("pattern,path", DIVERGES_FROM_GIT)
def test_diverges_from_git_exactly_where_intended(repo, pattern, path):
    repo.write(".gitignore", pattern + "\n")
    assert repo.check_ignore(path) is True, "git should match via the directory"
    assert matches(pattern, path) is False, "CODEOWNERS should not"
