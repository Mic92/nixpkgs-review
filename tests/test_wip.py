#!/usr/bin/env python3

from nixpkgs_review.cli import main

from .conftest import Helpers


def test_wip_command(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        with open(nixpkgs.path.joinpath("pkg1.txt"), "w") as f:
            f.write("foo")
        path = main(
            "nixpkgs-review",
            ["wip", "--remote", str(nixpkgs.remote), "--run", "exit 0"],
        )
        report = helpers.load_report(path)
        assert report["built"] == ["pkg1"]
