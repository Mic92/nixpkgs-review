import os
from nixpkgs_review.cli import main
from .cli_mocks import CliTestCase, Mock, IgnoreArgument
from unittest.mock import patch, mock_open
from pathlib import Path
from typing import List, Tuple, Any


def dummy_api_response() -> List[Tuple[Any, Any]]:
    return [(IgnoreArgument, mock_open(read_data="{}")())]


class GithubActions(CliTestCase):
    def setUp(self) -> None:
        CliTestCase.setUp(self)
        os.environ["PR"] = "1"

    @patch("urllib.request.urlopen")
    def test_post_result(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = Mock(self, dummy_api_response())

        directory = Path(self.directory.name)
        nixpkgs_stub = directory.joinpath("nixpkgs")
        nixpkgs_stub.mkdir()
        os.environ["NIX_PATH"] = f"nixpkgs={nixpkgs_stub}"

        report = os.path.join(self.directory.name, "report.md")
        with open(report, "w") as f:
            f.write("")

        main(
            "nixpkgs-review", ["post-result"],
        )

    @patch("urllib.request.urlopen")
    def test_merge(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = Mock(self, dummy_api_response())
        main("nixpkgs-review", ["merge"])

    @patch("urllib.request.urlopen")
    def test_approve(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = Mock(self, dummy_api_response())
        main("nixpkgs-review", ["approve"])
