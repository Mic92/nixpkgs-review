import argparse
import os
import re
import subprocess
import sys
from contextlib import ExitStack
from typing import Any, List, Optional

from .review import CheckoutOption, Review, nix_shell
from .worktree import Worktree
from .buildenv import Buildenv


def parse_pr_numbers(number_args: List[str]) -> List[int]:
    prs: List[int] = []
    for arg in number_args:
        m = re.match(r"(\d+)-(\d+)", arg)
        if m:
            prs.extend(range(int(m.group(1)), int(m.group(2))))
        else:
            try:
                prs.append(int(arg))
            except ValueError:
                print(f"expected number, got {m}", file=sys.stderr)
                sys.exit(1)
    return prs


def pr_command(args: argparse.Namespace) -> None:
    chdir_nixpkgs_root()

    prs = parse_pr_numbers(args.number)
    use_ofborg_eval = args.eval == "ofborg"
    checkout_option = (
        CheckoutOption.MERGE if args.checkout == "merge" else CheckoutOption.COMMIT
    )

    contexts = []

    with ExitStack() as stack:
        for pr in prs:
            worktree = stack.enter_context(Worktree(f"pr-{pr}"))
            try:
                review = Review(
                    worktree_dir=worktree.worktree_dir,
                    build_args=args.build_args,
                    api_token=args.token,
                    use_ofborg_eval=use_ofborg_eval,
                    only_packages=set(args.package),
                    checkout=checkout_option,
                )
                contexts.append((pr, worktree, review.build_pr(pr)))
            except subprocess.CalledProcessError:
                print(
                    f"https://github.com/NixOS/nixpkgs/pull/{pr} failed to build",
                    file=sys.stderr,
                )

        for pr, worktree, attrs in contexts:
            print(f"https://github.com/NixOS/nixpkgs/pull/{pr}")
            os.environ["NIX_PATH"] = worktree.nixpkgs_path()
            nix_shell(attrs)

        if len(contexts) != len(prs):
            sys.exit(1)


def rev_command(args: argparse.Namespace) -> None:
    chdir_nixpkgs_root()
    with Worktree(f"rev-{args.commit}") as worktree:
        r = Review(
            worktree_dir=worktree.worktree_dir,
            build_args=args.build_args,
            only_packages=set(args.package),
        )
        r.review_commit(args.branch, args.commit)


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
    rev_parser.set_defaults(func=rev_command)
    return rev_parser


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
    ]

    for flag in common_flags:
        pr_parser.add_argument(*flag.args, **flag.kwargs)
        rev_parser.add_argument(*flag.args, **flag.kwargs)

    return parser.parse_args(args)


def die(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def find_nixpkgs_root() -> Optional[str]:
    prefix = ["."]
    release_nix = ["nixos", "release.nix"]
    while True:
        root_path = os.path.join(*prefix)
        release_nix_path = os.path.join(root_path, *release_nix)
        if os.path.exists(release_nix_path):
            return root_path
        if os.path.abspath(root_path) == "/":
            return None
        prefix.append("..")


def chdir_nixpkgs_root() -> None:
    root = find_nixpkgs_root()
    if root is None:
        die("Has to be executed from nixpkgs repository")
    else:
        os.chdir(root)


def main(command: str, raw_args: List[str]) -> None:
    args = parse_args(command, raw_args)

    with Buildenv():
        args.func(args)
