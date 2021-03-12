import argparse
from pathlib import Path

from ..buildenv import Buildenv
from ..review import review_local_revision
from ..utils import verify_commit_hash


def rev_command(args: argparse.Namespace) -> Path:
    with Buildenv():
        commit = verify_commit_hash(args.commit)
        return review_local_revision(f"rev-{commit}", args, commit, args.pkgs)
