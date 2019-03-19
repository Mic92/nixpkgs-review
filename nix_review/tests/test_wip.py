import unittest

from typing import Any, List, Tuple
from unittest.mock import MagicMock, patch

from io import StringIO

from nix_review.cli import main

from .cli_mocks import (
    CliTestCase,
    build_cmds,
    Mock,
    IgnoreArgument,
    MockCompletedProcess,
    read_asset,
)


def wip_command_cmds() -> List[Tuple[Any, Any]]:
    return [
        (
            ["git", "rev-parse", "--verify", "HEAD"],
            MockCompletedProcess(stdout=b"hash1\n"),
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
            MockCompletedProcess(stdout=b"hash1\n"),
        ),
        (["git", "worktree", "add", IgnoreArgument, "hash1"], MockCompletedProcess()),
        (IgnoreArgument, MockCompletedProcess(stdout=StringIO("<items></items>"))),
        (["git", "apply"], MockCompletedProcess()),
        (
            IgnoreArgument,
            MockCompletedProcess(stdout=StringIO(read_asset("package_list_after.txt"))),
        ),
    ]


class WipCommand(CliTestCase):
    @patch("subprocess.run")
    @patch("subprocess.Popen")
    def test_wip_command(self, mock_popen: MagicMock, mock_run: MagicMock) -> None:
        effects = Mock(self, wip_command_cmds() + build_cmds)
        mock_run.side_effect = effects

        popen_instance = mock_popen.return_value
        popen_instance.__enter__.side_effect = effects

        main(
            "nix-review",
            [
                "wip",
                "--build-args",
                '--builders "ssh://joerg@10.243.29.170 aarch64-linux"',
            ],
        )


if __name__ == "__main__":
    unittest.main(failfast=True)
