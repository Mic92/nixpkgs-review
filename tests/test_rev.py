#!/usr/bin/env python3

import pytest
import shutil
import subprocess

from nixpkgs_review.cli import main

from .conftest import Helpers


@pytest.mark.skipif(not shutil.which("nom"), reason="`nom` not found in PATH")
def test_rev_command(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        with open(nixpkgs.path.joinpath("pkg1.txt"), "w") as f:
            f.write("foo")
        subprocess.run(["git", "add", "."])
        subprocess.run(["git", "commit", "-m", "example-change"])
        path = main(
            "nixpkgs-review",
            ["rev", "HEAD", "--remote", str(nixpkgs.remote), "--run", "exit 0"],
        )
        report = helpers.load_report(path)
        assert report["built"] == ["pkg1"]


def test_rev_command_without_nom(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        with open(nixpkgs.path.joinpath("pkg1.txt"), "w") as f:
            f.write("foo")
        subprocess.run(["git", "add", "."])
        subprocess.run(["git", "commit", "-m", "example-change"])
        path = main(
            "nixpkgs-review",
            [
                "rev",
                "HEAD",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--nom-path",
                "",
            ],
        )
        report = helpers.load_report(path)
        assert report["built"] == ["pkg1"]
