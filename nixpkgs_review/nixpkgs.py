"""Utilities for locating and identifying a nixpkgs git repository."""

from __future__ import annotations

import fcntl
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import IO, TYPE_CHECKING

from .errors import NixpkgsReviewError
from .utils import sh

if TYPE_CHECKING:
    from collections.abc import Iterator


def is_bare_repository() -> bool:
    """Check if CWD is inside a bare git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-bare-repository"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _is_bare_nixpkgs_repo() -> Path | None:
    """Check if CWD is a bare git repo containing nixpkgs.

    Returns the repo root path if so, None otherwise.
    """
    if not is_bare_repository():
        return None

    has_nixpkgs = subprocess.run(
        ["git", "cat-file", "-e", "HEAD:nixos/release.nix"],
        capture_output=True,
        check=False,
    )
    if has_nixpkgs.returncode != 0:
        return None

    return Path.cwd()


def find_nixpkgs_root() -> Path | None:
    """Find the root of a nixpkgs repository from CWD.

    Walks up from CWD looking for nixos/release.nix on disk.  If that fails,
    checks whether CWD is a bare nixpkgs repo (where the file exists only in
    the git tree, not on the filesystem).
    """
    root_path = Path.cwd()
    while True:
        if (root_path / "nixos" / "release.nix").exists():
            return root_path
        if root_path == root_path.parent:
            break
        root_path = root_path.parent

    return _is_bare_nixpkgs_repo()


def resolve_git_dir() -> Path:
    """Return the path to the git directory for the repo at CWD."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = "Cannot find git directory in current directory"
        raise NixpkgsReviewError(msg)
    return Path(result.stdout.strip())


@contextmanager
def locked_open(filename: Path, mode: str = "r") -> Iterator[IO[str]]:
    """
    This is a context manager that provides an advisory write lock on the file specified by `filename` when entering the context, and releases the lock when leaving the context.
    The lock is acquired using the `fcntl` module's `LOCK_EX` flag, which applies an exclusive write lock to the file.
    """
    with filename.open(mode) as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
        fcntl.flock(fd, fcntl.LOCK_UN)


def fetch_refs(repo: str, *refs: str, shallow_depth: int = 1) -> list[str]:
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    if shallow.returncode != 0:
        msg = f"Failed to detect if {repo} is shallow repository"
        raise NixpkgsReviewError(msg)

    fetch_cmd = [
        "git",
        "-c",
        "fetch.prune=false",
        "fetch",
        "--no-tags",
        "--force",
        repo,
    ]
    if shallow.stdout.strip() == "true":
        fetch_cmd.append(f"--depth={shallow_depth}")
    for i, ref in enumerate(refs):
        fetch_cmd.append(f"{ref}:refs/nixpkgs-review/{i}")
    dotgit = resolve_git_dir()
    with locked_open(dotgit / "nixpkgs-review", "w"):
        res = sh(fetch_cmd)
        if res.returncode != 0:
            msg = f"Failed to fetch {refs} from {repo}. git fetch failed with exit code {res.returncode}"
            raise NixpkgsReviewError(msg)
        shas = []
        for i, ref in enumerate(refs):
            rev_parse_cmd = ["git", "rev-parse", "--verify", f"refs/nixpkgs-review/{i}"]
            out = subprocess.run(
                rev_parse_cmd, text=True, stdout=subprocess.PIPE, check=False
            )
            if out.returncode != 0:
                msg = f"Failed to fetch {ref} from {repo} with command: {''.join(rev_parse_cmd)}"
                raise NixpkgsReviewError(msg)
            shas.append(out.stdout.strip())
        return shas
