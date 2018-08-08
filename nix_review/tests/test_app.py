import unittest
import os
import multiprocessing
from unittest.mock import patch, mock_open

from nix_review.app import main

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


class Mock:
    def __init__(self, test, arg_spec):
        self.test = test
        self.arg_spec_iterator = iter(arg_spec)
        self.expected_args = []
        self.ret = None

    def __iter__(self):
        return self

    def __call__(self, *args, **kwargs):
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


pkg_list = read_asset("package_list_after.txt").encode("utf-8")


def local_eval_cmds():
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
            0,
        ),
        (["git", "rev-parse", "--verify", "refs/nix-review/0"], b"hash1"),
        (["git", "rev-parse", "--verify", "refs/nix-review/1"], b"hash2"),
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
            b"<items></items>",
        ),
        (["git", "merge", "--no-commit", "hash2"], 0),
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
            pkg_list,
        ),
    ]


def borg_eval_cmds():
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
            0,
        ),
        (["git", "rev-parse", "--verify", "refs/nix-review/0"], b"hash1"),
        (["git", "rev-parse", "--verify", "refs/nix-review/1"], b"hash2"),
        (["git", "worktree", "add", "./.review/pr-37200", "hash1"], 0),
        (["git", "merge", "--no-commit", "hash2"], 0),
        (["nix", "eval", "--raw", "nixpkgs.system"], b"x86_64-linux"),
    ]


build_cmds = [
    (
        ["nix", "eval", "--json", IgnoreArgument],
        # hack to make sure the path exists
        b'{"pong3d": {"exists": true, "broken": false, "path": "'
        + __file__.encode("utf8")
        + b'"}}',
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
        0,
    ),
    (["nix-shell", "-p", "pong3d"], 0),
    (["git", "worktree", "prune"], 0),
]


class TestStringMethods(unittest.TestCase):
    def setUp(self):
        os.chdir(os.path.join(TEST_ROOT, "assets/nixpkgs"))

    @patch("urllib.request.urlopen")
    @patch("subprocess.Popen")
    @patch("subprocess.check_call")
    @patch("subprocess.check_output")
    def test_pr_local_eval(
        self, mock_check_output, mock_check_call, mock_popen, mock_urlopen
    ):
        effects = Mock(self, local_eval_cmds() + build_cmds)
        mock_check_call.side_effect = effects
        mock_popen.stdout.side_effect = effects
        mock_check_output.side_effect = effects
        mock_urlopen.side_effect = effects

        main(
            "nix-review",
            [
                "--build-args",
                '--builders "ssh://joerg@10.243.29.170 aarch64-linux"',
                "pr",
                "1",
            ],
        )

    @patch("urllib.request.urlopen")
    @patch("subprocess.Popen")
    @patch("subprocess.check_call")
    @patch("subprocess.check_output")
    def test_pr_borg_eval(
        self, mock_check_output, mock_check_call, mock_popen, mock_urlopen
    ):
        effects = Mock(self, borg_eval_cmds() + build_cmds)
        mock_check_call.side_effect = effects
        mock_popen.stdout.side_effect = effects
        mock_check_output.side_effect = effects
        mock_urlopen.side_effect = effects

        main(
            "nix-review",
            [
                "--build-args",
                '--builders "ssh://joerg@10.243.29.170 aarch64-linux"',
                "pr",
                "37200",
            ],
        )


if __name__ == "__main__":
    unittest.main(failfast=True)
