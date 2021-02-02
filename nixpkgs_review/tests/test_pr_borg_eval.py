import unittest
from typing import Any, List, Tuple
from unittest.mock import MagicMock, mock_open, patch

from nixpkgs_review.cli import main

from .cli_mocks import (
    CliTestCase,
    IgnoreArgument,
    Mock,
    MockCompletedProcess,
    build_cmds,
    read_asset,
)


def borg_eval_cmds() -> List[Tuple[Any, Any]]:
    return [
        (IgnoreArgument, mock_open(read_data=read_asset("github-pull-37200.json"))()),
        (
            IgnoreArgument,
            mock_open(read_data=read_asset("github-pull-37200-statuses.json"))(),
        ),
        (
            "https://gist.githubusercontent.com/GrahamcOfBorg/4c9ebc3e608308c6096202375b0dc902/raw/",
            read_asset("gist-37200.txt").encode("utf-8").split(b"\n"),
        ),
        (
            [
                "git",
                "-c",
                "fetch.prune=false",
                "fetch",
                "--force",
                "https://github.com/NixOS/nixpkgs",
                "master:refs/nixpkgs-review/0",
                "pull/37200/head:refs/nixpkgs-review/1",
            ],
            MockCompletedProcess(),
        ),
        (
            ["git", "rev-parse", "--verify", "refs/nixpkgs-review/0"],
            MockCompletedProcess(stdout="hash1\n"),
        ),
        (
            ["git", "rev-parse", "--verify", "refs/nixpkgs-review/1"],
            MockCompletedProcess(stdout="hash2\n"),
        ),
        (["git", "worktree", "add", IgnoreArgument, "hash1"], MockCompletedProcess()),
        (["git", "merge", "--no-commit", "--no-ff", "hash2"], MockCompletedProcess()),
        (
            [
                "nix",
                "--experimental-features",
                "nix-command",
                "eval",
                "--impure",
                "--raw",
                "--expr",
                "builtins.currentSystem",
            ],
            MockCompletedProcess(stdout="x86_64-linux"),
        ),
    ]


class PrCommandTestCase(CliTestCase):
    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_pr_command_borg_eval(
        self, mock_run: MagicMock, mock_urlopen: MagicMock
    ) -> None:
        effects = Mock(borg_eval_cmds() + build_cmds)
        mock_run.side_effect = effects
        mock_urlopen.side_effect = effects

        main(
            "nixpkgs-review",
            [
                "pr",
                "--build-args",
                '--builders "ssh://joerg@10.243.29.170 aarch64-linux"',
                "37200",
            ],
        )


if __name__ == "__main__":
    unittest.main(failfast=True)
