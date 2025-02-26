import shutil
from unittest.mock import MagicMock, patch

import pytest

from nixpkgs_review.cli import main

from .conftest import Helpers


@pytest.mark.skipif(not shutil.which("nom"), reason="`nom` not found in PATH")
def test_wip_command(helpers: Helpers, capfd: pytest.CaptureFixture) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
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
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
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


@patch("nixpkgs_review.review.list_packages")
def test_wip_only_packages_does_not_trigger_an_eval(
    mock_eval: MagicMock,
    helpers: Helpers,
    capfd: pytest.CaptureFixture,
) -> None:
    mock_eval.side_effect = RuntimeError
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
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
                "--package",
                "pkg1",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        captured = capfd.readouterr()
        assert "$ nix build" in captured.out
