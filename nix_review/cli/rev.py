import argparse
import subprocess

from ..worktree import Worktree
from ..review import Review


def rev_command(args: argparse.Namespace) -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", args.commit],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.decode("utf-8").strip()
    with Worktree(f"rev-{commit}") as worktree:
        review = Review(
            worktree_dir=worktree.worktree_dir,
            build_args=args.build_args,
            only_packages=set(args.package),
        )
        review.review_commit(args.branch, commit)
