import argparse
import subprocess

from ..builddir import Builddir
from ..review import Review


def rev_command(args: argparse.Namespace) -> None:
    commit = (
        subprocess.run(
            ["git", "rev-parse", "--verify", args.commit],
            check=True,
            stdout=subprocess.PIPE,
        )
        .stdout.decode("utf-8")
        .strip()
    )
    with Builddir(f"rev-{commit}") as builddir:
        review = Review(
            builddir=builddir,
            build_args=args.build_args,
            only_packages=set(args.package),
            package_regexes=args.package_regex,
        )
        review.review_commit(args.branch, commit)
