import os
from unittest.mock import MagicMock, mock_open, patch

from nixpkgs_review.cli import main

from .conftest import Helpers


@patch("urllib.request.urlopen")
def test_post_result(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        os.environ["PR"] = "1"
        os.environ["NIX_PATH"] = f"nixpkgs={nixpkgs.path}"
        os.environ["GITHUB_TOKEN"] = "foo"
        mock_urlopen.side_effect = [mock_open(read_data="{}")()]

        report = nixpkgs.path.joinpath("..", "report.md")
        with open(report, "w") as f:
            f.write("")

        main("nixpkgs-review", ["post-result"])


@patch("urllib.request.urlopen")
def test_merge(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.save_environ():
        os.environ["PR"] = "1"
        os.environ["GITHUB_TOKEN"] = "foo"
        mock_urlopen.side_effect = [mock_open(read_data="{}")()]
        main("nixpkgs-review", ["merge"])


@patch("urllib.request.urlopen")
def test_approve(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.save_environ():
        os.environ["PR"] = "1"
        os.environ["GITHUB_TOKEN"] = "foo"
        mock_urlopen.side_effect = [mock_open(read_data="{}")()]
        main("nixpkgs-review", ["approve"])
