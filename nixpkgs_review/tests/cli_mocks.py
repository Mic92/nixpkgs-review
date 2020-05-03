import os
from io import StringIO
from tempfile import TemporaryDirectory
from typing import Any, List, Optional, Tuple, Union, Type
from unittest import TestCase

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
    def __init__(self, stdout: Optional[Union[str, StringIO]] = None) -> None:
        self.returncode = 0
        self.stdout = stdout


class Mock:
    def __init__(self, arg_spec: List[Tuple[Any, Any]]) -> None:
        self.arg_spec_iterator = iter(arg_spec)

    def __iter__(self) -> "Mock":
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        expected_args, ret = next(self.arg_spec_iterator)
        if DEBUG:
            print(f"({expected_args}) -> {ret}")
        if expected_args is IgnoreArgument:
            return ret
        if len(args[0]) == len(expected_args):
            for (i, arg) in enumerate(expected_args):
                if arg is IgnoreArgument:
                    args[0][i] = IgnoreArgument
        if expected_args != args[0]:
            raise MockError(f"expected {expected_args}\n got {args[0]}")
        return ret


class CliTestCase(TestCase):
    def setUp(self) -> None:
        os.chdir(os.path.join(TEST_ROOT, "assets/nixpkgs"))
        self.directory = TemporaryDirectory()
        os.environ["HOME"] = self.directory.name
        os.environ["GITHUB_TOKEN"] = "0000000000000000000000000000000000000000"

    def tearDown(self) -> None:
        self.directory.cleanup()


build_cmds = [
    (
        ["nix", "eval", "--json", IgnoreArgument],
        # hack to make sure the path exists
        MockCompletedProcess(
            stdout=(
                '{"pong3d": {"exists": true, "broken": false, "path": "%s", "drvPath": "%s"}}'
                % (__file__, __file__)
            )
        ),
    ),
    (
        [
            "nix",
            "build",
            "--no-link",
            "--keep-going",
            "--option",
            "build-use-sandbox",
            "relaxed",
            "-f",
            IgnoreArgument,
            "--builders",
            "ssh://joerg@10.243.29.170 aarch64-linux",
        ],
        MockCompletedProcess(),
    ),
    (["nix-store", "--verify-path", IgnoreArgument], MockCompletedProcess()),
    (["nix", "log", IgnoreArgument], MockCompletedProcess()),
    (["nix-shell", IgnoreArgument], MockCompletedProcess()),
    (["git", "worktree", "prune"], MockCompletedProcess()),
]
