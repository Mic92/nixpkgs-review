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


def get_static_package(package: str) -> str:
    """Get path for static package, caching the result in environment variables."""
    env_var = f"TEST_{package.upper()}_PATH"
    if env_var in os.environ:
        return os.environ[env_var]

    project_root = Path(__file__).parent.parent.resolve()
    result = subprocess.run(
        [
            "nix",
            "build",
            "--extra-experimental-features",
            "nix-command flakes",
            "--inputs-from",
            str(project_root),
            "--no-link",
            "--print-out-paths",
            f"nixpkgs#pkgsStatic.{package}.out",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    path = result.stdout.strip()
    os.environ[env_var] = path
    return path


def real_nixpkgs() -> str:
    if "TEST_NIXPKGS_PATH" in os.environ:
        return os.environ["TEST_NIXPKGS_PATH"]

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
    path = proc.stdout.strip()
    os.environ["TEST_NIXPKGS_PATH"] = path
    return path


def setup_nixpkgs(target: Path) -> Path:
    shutil.copytree(
        Helpers.root().joinpath("assets/nixpkgs"),
        target,
        dirs_exist_ok=True,
    )

    # Get bash and coreutils from environment or build them using flakes
    bash_source = get_static_package("bash")
    coreutils_source = get_static_package("coreutils")
    nixpkgs_path = real_nixpkgs()

    # Store original paths for isolated store setup
    bash_source_path = bash_source
    coreutils_source_path = coreutils_source

    # Copy bash and coreutils to a writable location for tests
    test_bin_dir = target.joinpath("bin")
    test_bin_dir.mkdir(exist_ok=True)

    # Copy bash executable
    bash_dest = test_bin_dir / "bash"
    shutil.copy2(f"{bash_source}/bin/bash", bash_dest)
    bash_dest.chmod(0o755)

    # Copy coreutils directory
    coreutils_dest = test_bin_dir / "coreutils"
    shutil.copytree(f"{coreutils_source}/bin", coreutils_dest, dirs_exist_ok=True)

    # Make all coreutils executable
    for exe in coreutils_dest.glob("*"):
        if exe.is_file():
            exe.chmod(0o755)

    # Store the source paths in the target for later use by nixpkgs context
    (target / ".bash_source").write_text(bash_source_path)
    (target / ".coreutils_source").write_text(coreutils_source_path)

    # Substitute the config.nix.in template
    config_in = target.joinpath("config.nix.in")
    config_out = target.joinpath("config.nix")

    if config_in.exists():
        content = config_in.read_text()
        # Use paths without quotes so Nix treats them as paths and copies them to the store
        content = content.replace("@bash@", f"{bash_source_path}/bin/bash")
        content = content.replace("@coreutils@", f"{coreutils_source_path}/bin")
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
        return cast("dict[str, Any]", json.loads(data))

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

            # Get bash, coreutils, and nixpkgs BEFORE setting up isolated environment
            # This ensures they're built once and cached for all tests
            get_static_package("bash")
            get_static_package("coreutils")
            real_nixpkgs()

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

            # Disable sandbox for tests (for macOS compatibility)
            os.environ["_NIX_TEST_NO_SANDBOX"] = "1"

            # Disable Nix daemon for isolated environment
            if "NIX_REMOTE" in os.environ:
                del os.environ["NIX_REMOTE"]

            setup_nixpkgs(nixpkgs_path)

            with Chdir(nixpkgs_path):
                yield setup_git(nixpkgs_path)


@pytest.fixture
def helpers() -> type[Helpers]:
    return Helpers
