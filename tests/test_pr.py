#!/usr/bin/env python3

import subprocess

from nixpkgs_review.cli import main

from .conftest import Helpers


def test_pr_local_eval(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        with open(nixpkgs.path.joinpath("pkg1.txt"), "w") as f:
            f.write("foo")
        subprocess.run(["git", "add", "."])
        subprocess.run(["git", "commit", "-m", "example-change"])
        subprocess.run(["git", "checkout", "-b", "pull/1/head"])
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/head"])

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "1",
            ],
        )
        report = helpers.load_report(path)
        assert report["built"] == ["pkg1"]
