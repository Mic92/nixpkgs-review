from __future__ import annotations

from typing import TYPE_CHECKING

from nixpkgs_review import git
from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.buildenv import Buildenv
from nixpkgs_review.review import review_local_revision

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def wip_command(args: argparse.Namespace) -> Path:
    allow = AllowedFeatures(args.allow)
    with Buildenv(
        allow.aliases, args.extra_nixpkgs_config, args.extra_nixpkgs_args
    ) as buildenv:
        return review_local_revision(
            f"rev-{git.verify_commit_hash('HEAD')}-dirty",
            args,
            allow,
            buildenv,
            None,
            staged=args.staged,
            print_result=args.print_result,
        )
