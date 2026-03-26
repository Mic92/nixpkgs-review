"""Tests for nixpkgs repository detection (nixpkgs_review.nixpkgs)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from nixpkgs_review.nixpkgs import find_nixpkgs_root, is_bare_repository, resolve_git_dir

from .conftest import Chdir, Helpers


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def make_bare_with_dotgit(path: Path) -> Path:
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

    git(repo, "init", "-b", "master")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")

    # Set core.bare = true and remove working tree files
    git(repo, "config", "core.bare", "true")
    for child in repo.iterdir():
        if child.name != ".git":
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    return repo


def test_find_nixpkgs_root_in_bare_repo_with_dotgit(helpers: Helpers) -> None:
    """find_nixpkgs_root() should detect a bare nixpkgs repo that has a .git/ directory."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = make_bare_with_dotgit(path)

        with Chdir(bare_root):
            result = find_nixpkgs_root()
            assert result is not None
            assert result == bare_root


def make_true_bare(path: Path, *, with_nixpkgs: bool = True) -> Path:
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

    git(src, "init", "-b", "master")
    git(src, "add", ".")
    git(src, "commit", "-m", "init")

    bare = path / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", str(src), str(bare)],
        check=True,
    )
    return bare


def test_find_nixpkgs_root_in_true_bare_repo(helpers: Helpers) -> None:
    """find_nixpkgs_root() should detect a true bare nixpkgs repo (no .git directory)."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = make_true_bare(path, with_nixpkgs=True)

        with Chdir(bare_root):
            result = find_nixpkgs_root()
            assert result is not None
            assert result == bare_root


def test_resolve_git_dir_in_true_bare_repo(helpers: Helpers) -> None:
    """resolve_git_dir() should work in a true bare repo (no .git file or directory)."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = make_true_bare(path, with_nixpkgs=True)

        with Chdir(bare_root):
            git_dir = resolve_git_dir()
            assert git_dir.resolve() == bare_root.resolve()


def test_resolve_git_dir_in_bare_repo_with_dotgit(helpers: Helpers) -> None:
    """resolve_git_dir() should work in a bare repo that has a .git/ directory."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = make_bare_with_dotgit(path)

        with Chdir(bare_root):
            git_dir = resolve_git_dir()
            assert git_dir == Path(".git")


def test_is_bare_repository_true_for_bare(helpers: Helpers) -> None:
    """is_bare_repository() returns True inside a bare repo."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = make_bare_with_dotgit(path)

        with Chdir(bare_root):
            assert is_bare_repository() is True


def test_is_bare_repository_false_for_normal(helpers: Helpers) -> None:
    """is_bare_repository() returns False inside a normal repo."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        repo = path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("hi")
        git(repo, "init", "-b", "master")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "init")

        with Chdir(repo):
            assert is_bare_repository() is False


def test_wip_command_fails_in_bare_repo(helpers: Helpers) -> None:
    """wip command should fail early with a clear message in a bare repo."""
    with helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir).resolve()
        bare_root = make_bare_with_dotgit(path)
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

        git(repo, "init", "-b", "master")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "init")
        git(repo, "config", "core.bare", "true")

        with Chdir(repo):
            result = find_nixpkgs_root()
            assert result is None
