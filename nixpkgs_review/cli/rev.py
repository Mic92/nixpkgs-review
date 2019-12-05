import argparse

from ..utils import verify_commit_hash
from ..review import review_local_revision


def rev_command(args: argparse.Namespace) -> None:
    commit = verify_commit_hash(args.commit)
    review_local_revision(f"rev-{commit}", args, commit)
