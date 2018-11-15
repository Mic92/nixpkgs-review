import unittest
from typing import Any, List, Tuple
from unittest.mock import MagicMock, mock_open, patch

from nix_review.cli import main

from .cli_mocks import (
    CliTestCase,
    IgnoreArgument,
    Mock,
    MockCompletedProcess,
    build_cmds,
    read_asset,
)


def local_eval_cmds() -> List[Tuple[Any, Any]]:
    return [
        (IgnoreArgument, mock_open(read_data=read_asset("github-pull-1.json"))()),
        (
            IgnoreArgument,
            mock_open(read_data=read_asset("github-pull-1-statuses.json"))(),
        ),
        (
            [
                "git",
                "fetch",
                "--force",
                "https://github.com/NixOS/nixpkgs",
                "master:refs/nix-review/0",
                "pull/1/head:refs/nix-review/1",
            ],
            MockCompletedProcess(),
        ),
        (
            ["git", "rev-parse", "--verify", "refs/nix-review/0"],
            MockCompletedProcess(stdout=b"hash1\n"),
        ),
        (
            ["git", "rev-parse", "--verify", "refs/nix-review/1"],
            MockCompletedProcess(stdout=b"hash2\n"),
        ),
        (["git", "worktree", "add", "./.review/pr-1", "hash1"], 0),
        (
            [
                "nix-env",
                "-f",
                "./.review/pr-1",
                "-qaP",
                "--xml",
                "--out-path",
                "--show-trace",
            ],
            MockCompletedProcess(stdout=b"<items></items>"),
        ),
        (["git", "merge", "--no-commit", "hash2"], MockCompletedProcess()),
        (
            [
                "nix-env",
                "-f",
                "./.review/pr-1",
                "-qaP",
                "--xml",
                "--out-path",
                "--show-trace",
                "--meta",
            ],
            MockCompletedProcess(
                stdout=read_asset("package_list_after.txt").encode("utf-8")
            ),
        ),
    ]


class PrCommandTestcase(CliTestCase):
    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_local_eval(self, mock_run: MagicMock, mock_urlopen: MagicMock) -> None:
        effects = Mock(self, local_eval_cmds() + build_cmds)
        mock_urlopen.side_effect = effects
        mock_run.side_effect = effects

        main(
            "nix-review",
            [
                "pr",
                "--build-args",
                '--builders "ssh://joerg@10.243.29.170 aarch64-linux"',
                "1",
            ],
        )


if __name__ == "__main__":
    unittest.main(failfast=True)
