import shutil
import subprocess

import pytest

from nixpkgs_review.cli import main

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
        helpers.assert_built(pkg_name="pkg1", path=path)


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
        helpers.assert_built(pkg_name="pkg1", path=path)
