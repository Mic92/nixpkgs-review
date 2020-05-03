import argparse
import os
import re
from typing import Any, List, Pattern, Optional
from pathlib import Path

from .approve import approve_command
from .merge import merge_command
from .post_result import post_result_command
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
    pr_parser.add_argument(
        "--post-result",
        action="store_true",
        help="Post the nixpkgs-review results as a PR comment",
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


def read_github_token() -> Optional[str]:
    # for backwards compatibility we also accept GITHUB_OAUTH_TOKEN.
    token = os.environ.get("GITHUB_OAUTH_TOKEN", os.environ.get("GITHUB_TOKEN"))
    if token:
        return token
    raw_hub_path = os.environ.get("HUB_CONFIG", None)
    if raw_hub_path:
        hub_path = Path(raw_hub_path)
    else:
        raw_config_home = os.environ.get("XDG_CONFIG_HOME", None)
        if raw_config_home is None:
            home = os.environ.get("HOME", None)
            if home is None:
                return None
            config_home = Path(home).joinpath(".config")
        else:
            config_home = Path(raw_config_home)
        hub_path = config_home.joinpath("hub")
    try:
        with open(hub_path) as f:
            for line in f:
                token_match = re.match(r"\s*oauth_token:\s+([a-f0-9]+)", line)
                if token_match:
                    return token_match.group(1)
    except OSError:
        pass
    return None


def common_flags() -> List[CommonFlag]:
    return [
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
        CommonFlag(
            "--token",
            type=str,
            default=read_github_token(),
            help="Github access token (optional if request limit exceeds)",
        ),
    ]


def parse_args(command: str, args: List[str]) -> argparse.Namespace:
    main_parser = argparse.ArgumentParser(
        prog=command, formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    subparsers = main_parser.add_subparsers(
        dest="subcommand",
        title="subcommands",
        description="valid subcommands",
        help="use --help on the additional subcommands",
    )
    subparsers.required = True

    post_result_parser = subparsers.add_parser(
        "post-result", help="post PR comments with results"
    )
    post_result_parser.set_defaults(func=post_result_command)

    approve_parser = subparsers.add_parser("approve", help="approve PR")
    approve_parser.set_defaults(func=approve_command)

    merge_parser = subparsers.add_parser("merge", help="merge PR")
    merge_parser.set_defaults(func=merge_command)

    parsers = [
        approve_parser,
        merge_parser,
        post_result_parser,
        pr_flags(subparsers),
        rev_flags(subparsers),
        wip_flags(subparsers),
    ]

    common = common_flags()
    for parser in parsers:
        for flag in common:
            parser.add_argument(*flag.args, **flag.kwargs)

    return main_parser.parse_args(args)


def main(command: str, raw_args: List[str]) -> None:
    args = parse_args(command, raw_args)
    args.func(args)
