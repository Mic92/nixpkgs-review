import argparse
from pathlib import Path

from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.buildenv import Buildenv
from nixpkgs_review.review import review_local_revision
from nixpkgs_review.utils import verify_commit_hash


def wip_command(args: argparse.Namespace) -> Path:
    allow = AllowedFeatures(args.allow)
    with Buildenv(allow.aliases, args.extra_nixpkgs_config) as nixpkgs_config:
        return review_local_revision(
            f"rev-{verify_commit_hash('HEAD')}-dirty",
            args,
            allow,
            nixpkgs_config,
            None,
            args.staged,
            args.print_result,
        )
