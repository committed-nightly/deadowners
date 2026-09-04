from __future__ import annotations

import os
import subprocess

import pytest


def git(*args: str, cwd: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, check=True
    )
    return proc.stdout.decode()


class Repo:
    """A throwaway git repository with a few files and a CODEOWNERS."""

    def __init__(self, path: str) -> None:
        self.path = path

    def write(self, relpath: str, text: str = "x\n") -> None:
        full = os.path.join(self.path, relpath)
        os.makedirs(os.path.dirname(full) or self.path, exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(text)

    def add_files(self, *relpaths: str) -> None:
        for relpath in relpaths:
            self.write(relpath)

    def codeowners(self, text: str, where: str = ".github/CODEOWNERS") -> None:
        self.write(where, text)

    def commit(self, message: str = "wip") -> str:
        git("add", "-A", cwd=self.path)
        git("commit", "-m", message, cwd=self.path)
        return git("rev-parse", "HEAD", cwd=self.path).strip()

    def check_ignore(self, path: str) -> bool:
        """What real git thinks, for the pattern currently in .gitignore."""
        proc = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=self.path,
            capture_output=True,
        )
        return proc.returncode == 0


@pytest.fixture
def repo(tmp_path) -> Repo:
    path = str(tmp_path / "repo")
    os.makedirs(path)
    git("init", "-q", ".", cwd=path)
    # Local identity so the suite does not depend on the machine having one.
    git("config", "user.email", "test@example.invalid", cwd=path)
    git("config", "user.name", "test", cwd=path)
    git("config", "commit.gpgsign", "false", cwd=path)
    return Repo(path)
