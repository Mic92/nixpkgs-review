import argparse
from pathlib import Path

from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.buildenv import Buildenv
from nixpkgs_review.review import review_local_revision
from nixpkgs_review.utils import verify_commit_hash


def rev_command(args: argparse.Namespace) -> Path:
    allow = AllowedFeatures(args.allow)
    with Buildenv(allow.aliases, args.extra_nixpkgs_config) as nixpkgs_config:
        commit = verify_commit_hash(args.commit)
        return review_local_revision(
            f"rev-{commit}",
            args,
            allow,
            nixpkgs_config,
            commit,
            print_result=args.print_result,
        )
