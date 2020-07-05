import os
from pathlib import Path
from typing import Any, List, Tuple
from unittest.mock import MagicMock, mock_open, patch

from nixpkgs_review.cli import main

from .cli_mocks import CliTestCase, IgnoreArgument, Mock, MockCompletedProcess


def dummy_api_response() -> List[Tuple[Any, Any]]:
    return [(IgnoreArgument, mock_open(read_data="{}")())]


class GithubActions(CliTestCase):
    def setUp(self) -> None:
        CliTestCase.setUp(self)
        os.environ["PR"] = "1"

    @patch("subprocess.run")
    @patch("urllib.request.urlopen")
    def test_post_result(self, mock_run: MagicMock, mock_urlopen: MagicMock) -> None:
        directory = Path(self.directory.name)
        nix_instantiate = [
            (
                ["nix-instantiate", "--find-file", "nixpkgs"],
                MockCompletedProcess(stdout=str(directory.joinpath("nixpkgs"))),
            )
        ]
        effects = Mock(nix_instantiate + dummy_api_response())
        mock_urlopen.side_effect = effects
        mock_run.side_effect = effects

        report = os.path.join(self.directory.name, "report.md")
        with open(report, "w") as f:
            f.write("")

        print(os.environ["GITHUB_TOKEN"])

        main(
            "nixpkgs-review", ["post-result"],
        )

    @patch("urllib.request.urlopen")
    def test_merge(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = Mock(dummy_api_response())
        main("nixpkgs-review", ["merge"])

    @patch("urllib.request.urlopen")
    def test_approve(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = Mock(dummy_api_response())
        main("nixpkgs-review", ["approve"])
