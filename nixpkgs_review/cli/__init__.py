import argparse
import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from re import Pattern
from shutil import which
from typing import Any, cast

from ..utils import current_system, nix_nom_tool
from .approve import approve_command
from .comments import show_comments
from .merge import merge_command
from .post_result import post_result_command
from .pr import pr_command
from .rev import rev_command
from .wip import wip_command

try:
    import argcomplete
except ImportError:
    argcomplete = None


def regex_type(s: str) -> Pattern[str]:
    try:
        return re.compile(s)
    except re.error as e:
        raise argparse.ArgumentTypeError(f"'{s}' is not a valid regex: {e}")


def pr_flags(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
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


def rev_flags(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    rev_parser = subparsers.add_parser(
        "rev", help="review a change in the local pull request repository"
    )
    rev_parser.add_argument(
        "-b", "--branch", default="master", help="branch to compare against with"
    )
    rev_parser.add_argument(
        "commit", help="commit/tag/ref/branch in your local git repository"
    )

    rev_parser.set_defaults(func=rev_command)
    return rev_parser


def wip_flags(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    wip_parser = subparsers.add_parser(
        "wip", help="review the uncommitted changes in the working tree"
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

    wip_parser.set_defaults(func=wip_command)

    return wip_parser


class CommonFlag:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


def hub_config_path() -> Path:
    raw_hub_path = os.environ.get("HUB_CONFIG", None)
    if raw_hub_path:
        return Path(raw_hub_path)

    raw_config_home = os.environ.get("XDG_CONFIG_HOME", None)
    if raw_config_home is None:
        config_home = Path.home().joinpath(".config")
    else:
        config_home = Path(raw_config_home)
    return config_home.joinpath("hub")


def read_github_token() -> str | None:
    # for backwards compatibility we also accept GITHUB_OAUTH_TOKEN.
    token = os.environ.get("GITHUB_OAUTH_TOKEN", os.environ.get("GITHUB_TOKEN"))
    if token:
        return token
    try:
        with open(hub_config_path(), encoding="utf-8") as f:
            for line in f:
                # Allow substring match as hub uses yaml. Example string we match:
                # " - oauth_token: ghp_abcdefghijklmnopqrstuvwxyzABCDEF1234\n"
                token_match = re.search(
                    r"\s*oauth_token:\s+((?:gh[po]_)?[A-Za-z0-9]+)", line
                )
                if token_match:
                    return token_match.group(1)
    except OSError:
        pass
    if which("gh"):
        r = subprocess.run(["gh", "auth", "token"], stdout=subprocess.PIPE, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
    return None


def common_flags() -> list[CommonFlag]:
    return [
        CommonFlag(
            "--allow",
            action="append",
            default=[],
            choices=["aliases", "ifd", "url-literals"],
            help="Allow features that are normally disabled, can be passed multiple times",
        ),
        CommonFlag(
            "--build-args", default="", help="arguments passed to nix when building"
        ),
        CommonFlag(
            "--no-shell",
            action="store_true",
            help="Only evaluate and build without executing nix-shell",
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
            "-r",
            "--remote",
            default="https://github.com/NixOS/nixpkgs",
            help="Name of the nixpkgs repo to review",
        ),
        CommonFlag(
            "--run",
            type=str,
            default="",
            help="Passed to nix-shell to run a command instead of an interactive nix-shell",
        ),
        CommonFlag(
            "--sandbox",
            action="store_true",
            help="Wraps nix-shell inside a sandbox (requires `bwrap` in PATH)",
        ),
        CommonFlag(
            "-P",
            "--skip-package",
            action="append",
            default=[],
            help="Packages to not build (can be passed multiple times)",
        ),
        CommonFlag(
            "--skip-package-regex",
            action="append",
            default=[],
            type=regex_type,
            help="Regular expression that package attributes have not to match (can be passed multiple times)",
        ),
        CommonFlag(
            "--system",
            type=str,
            default=current_system(),
            help="Nix 'system' to evaluate and build packages for",
        ),
        CommonFlag(
            "--token",
            type=str,
            default=read_github_token(),
            help="Github access token (optional if request limit exceeds)",
        ),
        CommonFlag(
            "--build-graph",
            type=str,
            default=nix_nom_tool(),
            choices=["nix", "nom"],
            help='Build graph to print. Use either "nom" or "nix". Will default to "nom" if available',
        ),
        CommonFlag(
            "--print-result",
            action="store_true",
            help="Print the nixpkgs-review results to stdout",
        ),
        CommonFlag(
            "--extra-nixpkgs-config",
            type=str,
            default="{ }",
            help="Extra nixpkgs config to pass to `import <nixpkgs>`",
        ),
    ]


def parse_args(command: str, args: list[str]) -> argparse.Namespace:
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

    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve the current PR - meant to be used only inside a nixpkgs-review nix-shell",
    )
    approve_parser.set_defaults(func=approve_command)

    comments_parser = subparsers.add_parser(
        "comments",
        help="Show comments of the current PR - meant to be used only inside a nixpkgs-review nix-shell",
    )
    comments_parser.set_defaults(func=show_comments)

    merge_parser = subparsers.add_parser(
        "merge",
        help="Merge the current PR - meant to be used only inside a nixpkgs-review nix-shell",
    )
    merge_parser.set_defaults(func=merge_command)

    parsers = [
        approve_parser,
        comments_parser,
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

    try:
        version = metadata.version("nixpkgs_review")
    except metadata.PackageNotFoundError:
        version = "0.0.0"
    main_parser.add_argument(
        "--version",
        action="version",
        version=f"nixpkgs-review {version}",
    )

    if argcomplete:
        argcomplete.autocomplete(main_parser)

    if args == []:
        main_parser.print_help()
        sys.exit(2)

    return main_parser.parse_args(args)


def check_common_flags(args: argparse.Namespace) -> bool:
    if args.run == "":
        args.run = None
    elif args.no_shell:
        print("--no-shell and --run are mutually exclusive", file=sys.stderr)
        return False
    return True


def main(command: str, raw_args: list[str]) -> str:
    args = parse_args(command, raw_args)
    if not check_common_flags(args):
        sys.exit(1)
    return cast(str, args.func(args))
