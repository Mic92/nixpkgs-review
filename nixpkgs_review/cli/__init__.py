import argparse
import os
import re
from typing import Any, List, Pattern

from ..buildenv import Buildenv
from .pr import pr_command
from .rev import rev_command
from .wip import wip_command


def regex_type(s: str) -> Pattern[str]:
    try:
        return re.compile(s)
    except re.error as e:
        raise argparse.ArgumentTypeError(f"'{s}' is not a valid regex: {e}")


def pr_flags(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    pr_parser = subparsers.add_parser("pr", help="review a pull request on nixpkgs")
    pr_parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("GITHUB_OAUTH_TOKEN", None),
        help="Github access token (optional if request limit exceeds)",
    )
    pr_parser.add_argument(
        "--eval",
        default="ofborg",
        choices=["ofborg", "local"],
        help="Whether to use ofborg's evaluation result",
    )
    checkout_help = (
        "What to source checkout when building: "
        + "`merge` will merge the pull request into the target branch, "
        + "while `commit` will checkout pull request as the user has committed it"
    )

    pr_parser.add_argument(
        "-c",
        "--checkout",
        default="merge",
        choices=["merge", "commit"],
        help=checkout_help,
    )
    pr_parser.add_argument(
        "number",
        nargs="+",
        help="one or more nixpkgs pull request numbers (ranges are also supported)",
    )
    pr_parser.set_defaults(func=pr_command)
    return pr_parser


def rev_flags(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    rev_parser = subparsers.add_parser(
        "rev", help="review a change in the local pull request repository"
    )
    rev_parser.add_argument(
        "-b", "--branch", default="master", help="branch to compare against with"
    )
    rev_parser.add_argument(
        "commit", help="commit/tag/ref/branch in your local git repository"
    )
    rev_parser.add_argument(
        "-r",
        "--remote",
        default="https://github.com/NixOS/nixpkgs",
        help="Name of the nixpkgs repo to review",
    )
    rev_parser.set_defaults(func=rev_command)
    return rev_parser


def wip_flags(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    wip_parser = subparsers.add_parser(
        "wip", help="review the uncommited changes in the working tree"
    )

    wip_parser.add_argument(
        "-b", "--branch", default="master", help="branch to compare against with"
    )
    wip_parser.add_argument(
        "-s",
        "--staged",
        action="store_true",
        default=False,
        help="Whether to build staged changes",
    )
    wip_parser.add_argument(
        "-r",
        "--remote",
        default="https://github.com/NixOS/nixpkgs",
        help="Name of the nixpkgs repo to review",
    )

    wip_parser.set_defaults(func=wip_command)

    return wip_parser


class CommonFlag:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


def parse_args(command: str, args: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=command, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    subparsers = parser.add_subparsers(
        dest="subcommand",
        title="subcommands",
        description="valid subcommands",
        help="use --help on the additional subcommands",
    )
    subparsers.required = True  # type: ignore
    pr_parser = pr_flags(subparsers)
    rev_parser = rev_flags(subparsers)
    wip_parser = wip_flags(subparsers)

    common_flags = [
        CommonFlag(
            "--build-args", default="", help="arguments passed to nix when building"
        ),
        CommonFlag(
            "-p",
            "--package",
            action="append",
            default=[],
            help="Package to build (can be passed multiple times)",
        ),
        CommonFlag(
            "--package-regex",
            action="append",
            default=[],
            type=regex_type,
            help="Regular expression that package attributes have to match (can be passed multiple times)",
        ),
        CommonFlag(
            "--no-shell",
            action="store_true",
            help="Only evaluate and build without executing nix-shell",
        ),
    ]

    for flag in common_flags:
        pr_parser.add_argument(*flag.args, **flag.kwargs)
        rev_parser.add_argument(*flag.args, **flag.kwargs)
        wip_parser.add_argument(*flag.args, **flag.kwargs)

    return parser.parse_args(args)


def main(command: str, raw_args: List[str]) -> None:
    args = parse_args(command, raw_args)

    with Buildenv():
        args.func(args)
