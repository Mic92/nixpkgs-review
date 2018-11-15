from typing import Any, List, Tuple
from unittest.mock import MagicMock, patch

from nix_review.cli import main

from .cli_mocks import CliTestCase, Mock, MockCompletedProcess, build_cmds, read_asset


def rev_command_cmds() -> List[Tuple[Any, Any]]:
    return [
        (
            ["git", "rev-parse", "--verify", "HEAD"],
            MockCompletedProcess(stdout=b"hash1"),
        ),
        (
            [
                "git",
                "fetch",
                "--force",
                "https://github.com/NixOS/nixpkgs",
                "master:refs/nix-review/0",
            ],
            MockCompletedProcess(),
        ),
        (
            ["git", "rev-parse", "--verify", "refs/nix-review/0"],
            MockCompletedProcess(stdout=b"hash1"),
        ),
        (
            ["git", "worktree", "add", "./.review/rev-hash1", "hash1"],
            MockCompletedProcess(),
        ),
        (
            [
                "nix-env",
                "-f",
                "./.review/rev-hash1",
                "-qaP",
                "--xml",
                "--out-path",
                "--show-trace",
            ],
            MockCompletedProcess(stdout=b"<items></items>"),
        ),
        (["git", "merge", "--no-commit", "hash1"], MockCompletedProcess()),
        (
            [
                "nix-env",
                "-f",
                "./.review/rev-hash1",
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


class RevCommand(CliTestCase):
    @patch("subprocess.run")
    def test_rev_command(self, mock_run: MagicMock) -> None:
        effects = Mock(self, rev_command_cmds() + build_cmds)
        mock_run.side_effect = effects
        main(
            "nix-review",
            [
                "rev",
                "--build-args",
                '--builders "ssh://joerg@10.243.29.170 aarch64-linux"',
                "HEAD",
            ],
        )
