"""Thin wrappers over the ``git`` binary.

deadowners only needs two things from git: where the repository root is, and
the list of files in it. Both come from git rather than from walking the
filesystem, because the question the tool answers is about the files GitHub
can see -- not about node_modules, not about build output, and not about
whatever is left lying around in the working tree.
"""

from __future__ import annotations

import subprocess


class GitError(RuntimeError):
    """git was missing, unhappy, or pointed at something that isn't a repo."""


def run_git(args: list[str], cwd: str) -> str:
    """Run git and return stdout, or raise GitError."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, check=False
        )
    except FileNotFoundError as exc:  # pragma: no cover - depends on the box
        raise GitError("git is not on PATH") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(stderr or f"git {' '.join(args)} failed")
    return proc.stdout.decode("utf-8", "replace")


def repo_root(cwd: str) -> str:
    """Absolute path of the working tree containing ``cwd``."""
    return run_git(["rev-parse", "--show-toplevel"], cwd).strip()


def resolve(rev: str, cwd: str) -> str:
    """Resolve a revision to a full commit sha, raising GitError if unknown.

    ``--quiet`` means git says nothing at all when the name is unknown, so
    letting run_git raise would report the failed command line rather than
    the problem. The message people need is the name they typed.
    """
    try:
        out = run_git(
            ["rev-parse", "--verify", "--quiet", rev + "^{commit}"], cwd
        ).strip()
    except GitError as exc:
        detail = str(exc)
        if detail.startswith("git "):
            raise GitError(f"no such revision: {rev}") from exc
        raise
    if not out:
        raise GitError(f"no such revision: {rev}")
    return out


def tracked_files(cwd: str, ref: str | None = None) -> list[str]:
    """Every file git knows about, as repo-root-relative paths.

    ``-z`` throughout: a path with a newline in it is legal in git, rare, and
    exactly the sort of thing that would make a checker quietly miscount.
    """
    if ref is None:
        out = run_git(["ls-files", "-z", "--cached"], cwd)
    else:
        out = run_git(["ls-tree", "-r", "-z", "--name-only", ref], cwd)
    return [path for path in out.split("\0") if path]


def show(ref: str, relpath: str, cwd: str) -> str | None:
    """Contents of a file at a revision, or None if it isn't there."""
    try:
        return run_git(["show", f"{ref}:{relpath}"], cwd)
    except GitError:
        return None


def ls_tree_exists(ref: str, relpath: str, cwd: str) -> bool:
    out = run_git(["ls-tree", "--name-only", ref, relpath], cwd).strip()
    return bool(out)
