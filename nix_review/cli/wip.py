import argparse

from ..utils import verify_commit_hash
from ..review import review_local_revision


def wip_command(args: argparse.Namespace) -> None:
    review_local_revision(
        "rev-%s-dirty" % verify_commit_hash("HEAD"), args, None, args.staged
    )
