import argparse

from ..buildenv import Buildenv
from ..review import review_local_revision
from ..utils import verify_commit_hash


def wip_command(args: argparse.Namespace) -> None:
    with Buildenv():
        review_local_revision(
            "rev-%s-dirty" % verify_commit_hash("HEAD"), args, None, args.staged
        )
