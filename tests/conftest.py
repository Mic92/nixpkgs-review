#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

TEST_ROOT = Path(__file__).parent.resolve()
sys.path.append(str(TEST_ROOT.parent))


@dataclass
class Nixpkgs:
    path: Path
    remote: Path


def run(cmd: list[str | Path]) -> None:
    subprocess.run(cmd, check=True)


def real_nixpkgs() -> str:
    proc = subprocess.run(
        ["nix-instantiate", "--find-file", "nixpkgs"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if proc.returncode == 0:
        return proc.stdout.strip()

    proc = subprocess.run(
        [
            "nix",
            "eval",
            "--extra-experimental-features",
            "nix-command flakes",
            "--raw",
            "nixpkgs#path",
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return proc.stdout.strip()


def setup_nixpkgs(target: Path) -> Path:
    shutil.copytree(
        Helpers.root().joinpath("assets/nixpkgs"),
        target,
        dirs_exist_ok=True,
    )

    default_nix = target.joinpath("default.nix")

    with open(default_nix) as r:
        text = r.read().replace("@NIXPKGS@", real_nixpkgs())

    with open(default_nix, "w") as w:
        w.write(text)

    return target


class Chdir:
    def __init__(self, path: Path | str) -> None:
        self.old_dir = os.getcwd()
        self.new_dir = path

    def __enter__(self) -> None:
        os.chdir(self.new_dir)

    def __exit__(self, *args: Any) -> None:
        os.chdir(self.old_dir)


def setup_git(path: Path) -> Nixpkgs:
    os.environ["GIT_AUTHOR_NAME"] = "nixpkgs-review"
    os.environ["GIT_AUTHOR_EMAIL"] = "nixpkgs-review@example.com"
    os.environ["GIT_COMMITTER_NAME"] = "nixpkgs-review"
    os.environ["GIT_COMMITTER_EMAIL"] = "nixpkgs-review@example.com"

    run(["git", "-C", path, "init", "-b", "master"])
    run(["git", "-C", path, "add", "."])
    run(["git", "-C", path, "commit", "-m", "first commit"])

    remote = path.joinpath("remote")
    run(["git", "-C", path, "init", "--bare", str(remote)])
    run(["git", "-C", path, "remote", "add", "origin", str(remote)])
    run(["git", "-C", path, "push", "origin", "HEAD"])
    return Nixpkgs(path=path, remote=remote)


class Helpers:
    @staticmethod
    def root() -> Path:
        return TEST_ROOT

    @staticmethod
    def read_asset(asset: str) -> str:
        with open(os.path.join(TEST_ROOT, "assets", asset)) as f:
            return f.read()

    @staticmethod
    def load_report(review_dir: str) -> dict[str, Any]:
        with open(os.path.join(review_dir, "report.json")) as f:
            return cast(dict[str, Any], json.load(f))

    @staticmethod
    @contextmanager
    def save_environ() -> Iterator[None]:
        old = os.environ.copy()
        yield
        os.environ.clear()
        os.environ.update(old)

    @staticmethod
    @contextmanager
    def nixpkgs() -> Iterator[Nixpkgs]:
        with Helpers.save_environ(), tempfile.TemporaryDirectory() as tmpdirname:
            path = Path(tmpdirname)
            nixpkgs_path = path.joinpath("nixpkgs")
            os.environ["XDG_CACHE_HOME"] = str(path.joinpath("cache"))
            setup_nixpkgs(nixpkgs_path)

            with Chdir(nixpkgs_path):
                yield setup_git(nixpkgs_path)


# pytest.fixture is untyped
@pytest.fixture  # type: ignore
def helpers() -> type[Helpers]:
    return Helpers
