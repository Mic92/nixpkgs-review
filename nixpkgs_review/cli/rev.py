from __future__ import annotations

from typing import TYPE_CHECKING

from nixpkgs_review import git
from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.buildenv import Buildenv
from nixpkgs_review.review import review_local_revision

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def rev_command(args: argparse.Namespace) -> Path:
    allow = AllowedFeatures(args.allow)
    with Buildenv(allow.aliases, args.extra_nixpkgs_config) as nixpkgs_config:
        commit = git.verify_commit_hash(args.commit)
        return review_local_revision(
            f"rev-{commit}",
            args,
            allow,
            nixpkgs_config,
            commit,
            print_result=args.print_result,
        )
