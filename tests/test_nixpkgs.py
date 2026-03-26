"""Tests for nixpkgs repository detection (nixpkgs_review.nixpkgs)."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from nixpkgs_review.cli import main
from nixpkgs_review.nixpkgs import find_nixpkgs_root

from .conftest import Chdir, Helpers


GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@test",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@test",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, env={**os.environ, **GIT_ENV})


def _make_bare_with_dotgit(path: Path) -> Path:
    """Create a bare repo that has a .git/ directory and nixos/release.nix in its tree.

    This mimics the layout:
        path/
        ├── .git/          ← real directory, core.bare = true
        │   ├── HEAD
        │   ├── objects/
        │   └── ...
        └── (no working tree files)

    Returns the bare repo root.
    """
    # Create a normal repo with just nixos/release.nix
    repo = path / "repo"
    repo.mkdir()
    (repo / "nixos").mkdir()
    (repo / "nixos" / "release.nix").write_text("{}")

    _git(repo, "init", "-b", "master")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    # Set core.bare = true and remove working tree files
    _git(repo, "config", "core.bare", "true")
    for child in repo.iterdir():
        if child.name != ".git":
            if child.is_dir():
                import shutil

                shutil.rmtree(child)
            else:
                child.unlink()

    return repo


def test_find_nixpkgs_root_in_bare_repo_with_dotgit(helpers: Helpers) -> None:
    """find_nixpkgs_root() should detect a bare nixpkgs repo that has a .git/ directory."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = _make_bare_with_dotgit(path)

        with Chdir(bare_root):
            result = find_nixpkgs_root()
            assert result is not None
            assert result == bare_root


def _make_true_bare(path: Path, *, with_nixpkgs: bool = True) -> Path:
    """Create a true bare repo (git clone --bare style): no .git directory at all.

    The git database (HEAD, objects, refs, ...) lives directly in the returned directory.
    """
    # Create a normal repo first, then clone --bare
    src = path / "src"
    src.mkdir()
    if with_nixpkgs:
        (src / "nixos").mkdir()
        (src / "nixos" / "release.nix").write_text("{}")
    else:
        (src / "README.md").write_text("not nixpkgs")

    _git(src, "init", "-b", "master")
    _git(src, "add", ".")
    _git(src, "commit", "-m", "init")

    bare = path / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", str(src), str(bare)],
        check=True,
        env={**os.environ, **GIT_ENV},
    )
    return bare


def test_find_nixpkgs_root_in_true_bare_repo(helpers: Helpers) -> None:
    """find_nixpkgs_root() should detect a true bare nixpkgs repo (no .git directory)."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = _make_true_bare(path, with_nixpkgs=True)

        with Chdir(bare_root):
            result = find_nixpkgs_root()
            assert result is not None
            assert result == bare_root



def test_wip_command_fails_in_bare_repo(helpers: Helpers) -> None:
    """wip command should fail early with a clear message in a bare repo."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = _make_bare_with_dotgit(path)
        os.environ["XDG_CACHE_HOME"] = str(path / "cache")

        with Chdir(bare_root), pytest.raises(SystemExit, match="1"):
            from nixpkgs_review.cli import main

            main(
                "nixpkgs-review",
                ["wip", "--remote", str(bare_root), "--build-graph", "nix"],
            )


def test_find_nixpkgs_root_returns_none_for_non_nixpkgs_bare_repo(
    helpers: Helpers,
) -> None:
    """find_nixpkgs_root() should return None for a bare repo that isn't nixpkgs."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        repo = path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("not nixpkgs")

        _git(repo, "init", "-b", "master")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")
        _git(repo, "config", "core.bare", "true")

        with Chdir(repo):
            result = find_nixpkgs_root()
            assert result is None
