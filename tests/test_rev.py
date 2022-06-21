#!/usr/bin/env python3

import subprocess

from nixpkgs_review.cli import main

from .conftest import Helpers


def test_rev_command(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        # the commit is compared with the master branch,
        # so the commit must be on a separate branch.
        # if the commit is also on the master branch,
        # the rev command throws "nothing to compare"
        subprocess.run(["git", "checkout", "-b", "example-branch"])
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
