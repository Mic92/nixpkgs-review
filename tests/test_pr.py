#!/usr/bin/env python3

import pytest
import shutil
import subprocess

from nixpkgs_review.cli import main
from nixpkgs_review.utils import nix_nom_tool

from .conftest import Helpers
from unittest.mock import MagicMock, mock_open, patch


@patch("nixpkgs_review.utils.shutil.which", return_value=None)
def test_default_to_nix_if_nom_not_found(mock_shutil):
    return_value = nix_nom_tool()
    assert return_value == "nix"
    mock_shutil.assert_called_once()


@pytest.mark.skipif(not shutil.which("nom"), reason="`nom` not found in PATH")
def test_pr_local_eval(helpers: Helpers, capfd) -> None:
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
        captured = capfd.readouterr()
        assert "$ nom build" in captured.out


@pytest.mark.skipif(not shutil.which("nom"), reason="`nom` not found in PATH")
def test_pr_local_eval_custom_nom(helpers: Helpers, capfd) -> None:
    with helpers.nixpkgs() as nixpkgs:
        with open(nixpkgs.path.joinpath("pkg1.txt"), "w") as f:
            f.write("foo")
        subprocess.run(["git", "add", "."])
        subprocess.run(["git", "commit", "-m", "example-change"])
        subprocess.run(["git", "checkout", "-b", "pull/1/head"])
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/head"])
        custom_nom = shutil.which("nom")

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "1",
                "--nom-path",
                custom_nom,
            ],
        )
        report = helpers.load_report(path)
        assert report["built"] == ["pkg1"]
        captured = capfd.readouterr()
        print(captured)
        # the `custom_nom` has a full path
        assert f"{custom_nom} build --extra-experimental-features" in captured.out


@patch("nixpkgs_review.cli.nix_nom_tool", return_value="nix")
def test_pr_local_eval_missing_nom(mock_tool, helpers: Helpers, capfd) -> None:
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
        mock_tool.assert_called_once()
        captured = capfd.readouterr()
        assert "$ nix build" in captured.out


def test_pr_local_eval_without_nom(helpers: Helpers, capfd) -> None:
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
                "--nom-path",
                "",
            ],
        )
        report = helpers.load_report(path)
        assert report["built"] == ["pkg1"]
        captured = capfd.readouterr()
        assert "$ nix build" in captured.out


@pytest.mark.skipif(not shutil.which("bwrap"), reason="`bwrap` not found in PATH")
def test_pr_local_eval_with_sandbox(helpers: Helpers) -> None:
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
                "--sandbox",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "1",
            ],
        )
        report = helpers.load_report(path)
        assert report["built"] == ["pkg1"]


@patch("urllib.request.urlopen")
def test_pr_ofborg_eval(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        with open(nixpkgs.path.joinpath("pkg1.txt"), "w") as f:
            f.write("foo")
        subprocess.run(["git", "add", "."])
        subprocess.run(["git", "commit", "-m", "example-change"])
        subprocess.run(["git", "checkout", "-b", "pull/37200/head"])
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/37200/head"])

        mock_urlopen.side_effect = [
            mock_open(read_data=helpers.read_asset("github-pull-37200.json"))(),
            mock_open(
                read_data=helpers.read_asset("github-pull-37200-statuses.json")
            )(),
            helpers.read_asset("gist-37200.txt").encode("utf-8").split(b"\n"),
        ]

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "37200",
            ],
        )
        report = helpers.load_report(path)
        assert report["built"] == ["pkg1"]
