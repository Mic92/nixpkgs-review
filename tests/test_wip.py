#!/usr/bin/env python3

import shutil

import pytest

from nixpkgs_review.cli import main

from .conftest import Helpers


@pytest.mark.skipif(not shutil.which("nom"), reason="`nom` not found in PATH")
def test_wip_command(helpers: Helpers, capfd: pytest.CaptureFixture) -> None:
    with helpers.nixpkgs() as nixpkgs:
        with open(nixpkgs.path.joinpath("pkg1.txt"), "w") as f:
            f.write("foo")
        path = main(
            "nixpkgs-review",
            ["wip", "--remote", str(nixpkgs.remote), "--run", "exit 0"],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        captured = capfd.readouterr()
        assert "$ nom build" in captured.out


def test_wip_command_without_nom(
    helpers: Helpers, capfd: pytest.CaptureFixture
) -> None:
    with helpers.nixpkgs() as nixpkgs:
        with open(nixpkgs.path.joinpath("pkg1.txt"), "w") as f:
            f.write("foo")
        path = main(
            "nixpkgs-review",
            [
                "wip",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--build-graph",
                "nix",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        captured = capfd.readouterr()
        assert "$ nix build" in captured.out
