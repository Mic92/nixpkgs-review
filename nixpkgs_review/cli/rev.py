import argparse

from ..buildenv import Buildenv
from ..review import review_local_revision
from ..utils import verify_commit_hash


def rev_command(args: argparse.Namespace) -> None:
    with Buildenv():
        commit = verify_commit_hash(args.commit)
        review_local_revision(f"rev-{commit}", args, commit)
