from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nixpkgs_review.cli import main
from nixpkgs_review.utils import current_system

if TYPE_CHECKING:
    from .conftest import Helpers


@pytest.mark.skipif(not shutil.which("nom"), reason="`nom` not found in PATH")
def test_rev_command(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        path = main(
            "nixpkgs-review",
            ["rev", "HEAD", "--remote", str(nixpkgs.remote), "--run", "exit 0"],
        )
        helpers.assert_built(path, "pkg1")


def test_rev_command_with_tests(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        path = main(
            "nixpkgs-review",
            [
                "rev",
                "HEAD",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--build-graph",
                "nix",
                "--tests",
                "--skip-package-regex",
                r".*\.tests\.slow",
            ],
        )
        helpers.assert_built(path, "pkg1")
        report = helpers.load_report(path)
        tests = report["result"][current_system()]["tests"]
        assert [a["name"] for a in tests] == ["pkg1.tests.simple"]
        assert (Path(path) / "report.md").read_text().count(" --tests") == 1


def test_rev_command_without_nom(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        path = main(
            "nixpkgs-review",
            [
                "rev",
                "HEAD",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--build-graph",
                "nix",
            ],
        )
        helpers.assert_built(path, "pkg1")


@patch("nixpkgs_review.review.list_packages")
def test_rev_only_packages_does_not_trigger_an_eval(
    mock_eval: MagicMock,
    helpers: Helpers,
) -> None:
    mock_eval.side_effect = RuntimeError
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)

        path = main(
            "nixpkgs-review",
            [
                "rev",
                "HEAD",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--build-graph",
                "nix",
                "--package",
                "pkg1",
            ],
        )
        helpers.assert_built(path, "pkg1")


def test_rev_command_with_pkgs(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        path = main(
            "nixpkgs-review",
            [
                "rev",
                "HEAD",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--build-graph",
                "nix",
                "--pkgs",
                "pkgsAlt",
            ],
        )
        helpers.assert_built(path, "pkgsAlt.pkg1")


def test_rev_command_with_pkgs_and_package(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        path = main(
            "nixpkgs-review",
            [
                "rev",
                "HEAD",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--build-graph",
                "nix",
                "--pkgs",
                "pkgsAlt",
                "--package",
                "pkg1",
            ],
        )
        helpers.assert_built(path, "pkgsAlt.pkg1")


@pytest.mark.parametrize("pkg_count", [0, 1, 10, 51])
def test_rev_command_with_pkg_count(helpers: Helpers, pkg_count: int) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        path = main(
            "nixpkgs-review",
            [
                "rev",
                "HEAD",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--build-graph",
                "nix",
                "--extra-nixpkgs-config",
                f"{{ pkgCount = {pkg_count}; }}",
            ],
        )
        pkgs = {f"pkg{x + 1}" for x in range(pkg_count)}
        helpers.assert_built(path, *pkgs)
