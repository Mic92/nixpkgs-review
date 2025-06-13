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

from nixpkgs_review.utils import current_system

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

    # Get bash and coreutils from environment or build them
    bash_path = os.environ.get("TEST_BASH_PATH")
    if not bash_path:
        bash_path = subprocess.run(
            ["nix-build", "<nixpkgs>", "-A", "pkgsStatic.bash", "--no-out-link"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    coreutils_path = os.environ.get("TEST_COREUTILS_PATH")
    if not coreutils_path:
        coreutils_path = subprocess.run(
            ["nix-build", "<nixpkgs>", "-A", "pkgsStatic.coreutils", "--no-out-link"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    # Get the real nixpkgs path
    nixpkgs_path = os.environ.get("TEST_NIXPKGS_PATH")
    if not nixpkgs_path:
        nixpkgs_path = real_nixpkgs()

    # Substitute the config.nix.in template
    config_in = target.joinpath("config.nix.in")
    config_out = target.joinpath("config.nix")

    if config_in.exists():
        content = config_in.read_text()
        content = content.replace("@bash@", f"{bash_path}/bin/bash")
        content = content.replace("@coreutils@", f"{coreutils_path}/bin")
        content = content.replace("@lib@", f"(import {nixpkgs_path} {{}}).lib")
        config_out.write_text(content)

    return target


class Chdir:
    def __init__(self, path: Path | str) -> None:
        self.old_dir = Path.cwd()
        self.new_dir = path

    def __enter__(self) -> None:
        os.chdir(self.new_dir)

    def __exit__(self, *args: object) -> None:
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
        return (TEST_ROOT / "assets" / asset).read_text()

    @staticmethod
    def load_report(review_dir: str) -> dict[str, Any]:
        data = (Path(review_dir) / "report.json").read_text()
        return cast(dict[str, Any], json.loads(data))

    @staticmethod
    def assert_built(pkg_name: str, path: str) -> None:
        report = Helpers.load_report(path)
        assert report["result"][current_system()]["built"] == [pkg_name]

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

            # Set up isolated Nix environment for each test
            test_nix_dir = path.joinpath("test-nix")
            os.environ["NIX_STORE_DIR"] = str(test_nix_dir.joinpath("store"))
            os.environ["NIX_DATA_DIR"] = str(test_nix_dir.joinpath("share"))
            os.environ["NIX_LOG_DIR"] = str(test_nix_dir.joinpath("var/log/nix"))
            os.environ["NIX_STATE_DIR"] = str(test_nix_dir.joinpath("state"))
            os.environ["NIX_CONF_DIR"] = str(test_nix_dir.joinpath("etc"))

            # Create directories
            for env_var in [
                "NIX_STORE_DIR",
                "NIX_DATA_DIR",
                "NIX_LOG_DIR",
                "NIX_STATE_DIR",
                "NIX_CONF_DIR",
            ]:
                Path(os.environ[env_var]).mkdir(parents=True, exist_ok=True)

            # Disable substituters and sandboxing for tests
            os.environ["NIX_CONFIG"] = f"""
substituters =
connect-timeout = 0
sandbox = false
sandbox-build-dir = {test_nix_dir.joinpath("build")}
"""

            setup_nixpkgs(nixpkgs_path)

            with Chdir(nixpkgs_path):
                yield setup_git(nixpkgs_path)


@pytest.fixture
def helpers() -> type[Helpers]:
    return Helpers
