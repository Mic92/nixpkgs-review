import os
from typing import Any, List, Optional, Tuple
from unittest import TestCase
import multiprocessing

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
    def __init__(self, test: TestCase, arg_spec: List[Tuple[Any, Any]]) -> None:
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


class CliTestCase(TestCase):
    def setUp(self) -> None:
        os.chdir(os.path.join(TEST_ROOT, "assets/nixpkgs"))


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
