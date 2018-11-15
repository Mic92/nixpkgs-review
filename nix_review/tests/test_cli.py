import multiprocessing
import os
import unittest
from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock, mock_open, patch

from nix_review.cli import main

TEST_ROOT = os.path.dirname(os.path.realpath(__file__))
DEBUG = False


class IgnoreArgument:
    def __repr__(self) -> str:
        return "(ignored)"


def read_asset(asset: str) -> str:
    with open(os.path.join(TEST_ROOT, "assets", asset)) as f:
        return f.read()


class MockError(Exception):
    pass


class MockCompletedProcess:
    def __init__(self, stdout: Optional[bytes] = None) -> None:
        self.returncode = 0
        self.stdout = stdout


class Mock:
    def __init__(
        self, test: unittest.TestCase, arg_spec: List[Tuple[Any, Any]]
    ) -> None:
        self.test = test
        self.arg_spec_iterator = iter(arg_spec)
        self.expected_args: List[Any] = []
        self.ret = None

    def __iter__(self) -> "Mock":
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        (self.expected_args, self.ret) = next(self.arg_spec_iterator)
        if DEBUG:
            print(f"({self.expected_args}) -> {self.ret}")
        if self.expected_args is IgnoreArgument:
            return self.ret
        if len(args[0]) == len(self.expected_args):
            for (i, arg) in enumerate(self.expected_args):
                if arg is IgnoreArgument:
                    args[0][i] = IgnoreArgument
        if self.expected_args != args[0]:
            raise MockError(f"expected {self.expected_args}\n got {args[0]}")
        return self.ret


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
            MockCompletedProcess(stdout=b"hash1"),
        ),
        (
            ["git", "rev-parse", "--verify", "refs/nix-review/1"],
            MockCompletedProcess(stdout=b"hash2"),
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
                "fetch",
                "--force",
                "https://github.com/NixOS/nixpkgs",
                "master:refs/nix-review/0",
                "pull/37200/head:refs/nix-review/1",
            ],
            MockCompletedProcess(),
        ),
        (
            ["git", "rev-parse", "--verify", "refs/nix-review/0"],
            MockCompletedProcess(stdout=b"hash1"),
        ),
        (
            ["git", "rev-parse", "--verify", "refs/nix-review/1"],
            MockCompletedProcess(stdout=b"hash2"),
        ),
        (
            ["git", "worktree", "add", "./.review/pr-37200", "hash1"],
            MockCompletedProcess(),
        ),
        (["git", "merge", "--no-commit", "hash2"], MockCompletedProcess()),
        (
            ["nix", "eval", "--raw", "nixpkgs.system"],
            MockCompletedProcess(stdout=b"x86_64-linux"),
        ),
    ]


build_cmds = [
    (
        ["nix", "eval", "--json", IgnoreArgument],
        # hack to make sure the path exists
        MockCompletedProcess(
            stdout=(
                b'{"pong3d": {"exists": true, "broken": false, "path": "'
                + __file__.encode("utf8")
                + b'"}}'
            )
        ),
    ),
    (
        [
            "nix-shell",
            "--no-out-link",
            "--keep-going",
            "--max-jobs",
            str(multiprocessing.cpu_count()),
            "--option",
            "build-use-sandbox",
            "true",
            "--run",
            "true",
            "--builders",
            "ssh://joerg@10.243.29.170 aarch64-linux",
            "-p",
            "pong3d",
        ],
        MockCompletedProcess(),
    ),
    (["nix-store", "--verify-path", IgnoreArgument], MockCompletedProcess()),
    (["nix-shell", "-p", "pong3d"], MockCompletedProcess()),
    (["git", "worktree", "prune"], MockCompletedProcess()),
]


class TestStringMethods(unittest.TestCase):
    def setUp(self) -> None:
        os.chdir(os.path.join(TEST_ROOT, "assets/nixpkgs"))

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

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_pr_command_local_eval(
        self, mock_run: MagicMock, mock_urlopen: MagicMock
    ) -> None:
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

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_pr_command_borg_eval(
        self, mock_run: MagicMock, mock_urlopen: MagicMock
    ) -> None:
        effects = Mock(self, borg_eval_cmds() + build_cmds)
        mock_run.side_effect = effects
        mock_urlopen.side_effect = effects

        main(
            "nix-review",
            [
                "pr",
                "--build-args",
                '--builders "ssh://joerg@10.243.29.170 aarch64-linux"',
                "37200",
            ],
        )


if __name__ == "__main__":
    unittest.main(failfast=True)
