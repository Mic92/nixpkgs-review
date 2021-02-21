import argparse
from pathlib import Path

from ..buildenv import Buildenv
from ..review import review_local_revision
from ..utils import verify_commit_hash


def wip_command(args: argparse.Namespace) -> Path:
    with Buildenv():
        return review_local_revision(
            "rev-%s-dirty" % verify_commit_hash("HEAD"), args, None, args.staged
        )
