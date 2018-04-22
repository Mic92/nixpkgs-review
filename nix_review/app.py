import argparse
import sys
import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import List, Generator

from .utils import sh
from .review import Review


def pr_command(args: argparse.Namespace) -> None:
    with worktree(f"pr-{args.number}") as worktree_dir:
        r = Review(worktree_dir, args.build_args, args.token)
        r.review_pr(args.number)


def rev_command(args: argparse.Namespace) -> None:
    with worktree(f"rev-{args.commit}") as worktree_dir:
        r = Review(worktree_dir, args.build_args)
        r.review_commit(args.branch, args.commit)


def parse_args(command: str, args: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=command)
    parser.add_argument(
        "--build-args",
        default="",
        help="arguments passed to nix when building")
    subparsers = parser.add_subparsers(
        dest="subcommand",
        title="subcommands",
        description="valid subcommands",
        help="use --help on the additional subcommands")
    subparsers.required = True  # type: ignore

    pr_parser = subparsers.add_parser(
        "pr", help="review a pull request on nixpkgs")
    pr_parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("GITHUB_OAUTH_TOKEN", None),
        help="Github access token (optional if request limit exceeds)")
    pr_parser.add_argument(
        "number", type=int, help="the nixpkgs pull request number")
    pr_parser.set_defaults(func=pr_command)

    rev_parser = subparsers.add_parser(
        "rev", help="review a change in the local pull request repository")
    rev_parser.add_argument(
        "--branch", default="master", help="branch to compare against with")
    rev_parser.add_argument(
        "commit", help="commit/tag/ref/branch in your local git repository")
    rev_parser.set_defaults(func=rev_command)

    return parser.parse_args(args)


def die(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def find_nixpkgs_root() -> str:
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


@contextmanager
def worktree(name: str) -> Generator[str, None, None]:
    worktree_dir = os.path.join(f"./.review/{name}")
    os.makedirs(worktree_dir, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile() as cfg:
            cfg.write(b"pkgs: { allowUnfree = true; }")
            cfg.flush()
            os.environ["NIXPKGS_CONFIG"] = cfg.name
            os.environ[
                "NIX_PATH"] = f"nixpkgs={os.path.realpath(worktree_dir)}"
            yield worktree_dir
    finally:
        shutil.rmtree(worktree_dir)
        sh(["git", "worktree", "prune"])


def main(command: str, raw_args: List[str]) -> None:
    root = find_nixpkgs_root()
    if root is None:
        die("Has to be execute from nixpkgs repository")

    os.chdir(root)

    args = parse_args(command, raw_args)
    args.func(args)
