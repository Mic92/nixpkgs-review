import argparse
from pathlib import Path

from ..allow import AllowedFeatures
from ..buildenv import Buildenv
from ..review import review_local_revision
from ..utils import verify_commit_hash


def wip_command(args: argparse.Namespace) -> Path:
    allow = AllowedFeatures(args.allow)
    with Buildenv(allow.aliases):
        return review_local_revision(
            "rev-%s-dirty" % verify_commit_hash("HEAD"),
            args,
            allow,
            None,
            args.staged,
            args.print_result,
        )
