from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nixpkgs_review import git
from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.buildenv import Buildenv, is_bare_repository
from nixpkgs_review.review import (
    LocalRevisionTarget,
    ReviewAction,
    build_config_from_args,
    review_local_revision,
)
from nixpkgs_review.utils import die

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def wip_command(args: argparse.Namespace) -> Path:
    allow = AllowedFeatures(args.allow)
    with Buildenv(
        allow_aliases=allow.aliases, extra_nixpkgs_config=args.extra_nixpkgs_config
    ) as nixpkgs_config:
        if is_bare_repository():
            die(
                "The `wip` command requires a working tree, but the current repository "
                "is bare. Use `nixpkgs-review pr` or `nixpkgs-review rev <commit>` instead."
            )
        return review_local_revision(
            f"rev-{git.verify_commit_hash('HEAD')}-dirty",
            args,
            partial(build_config_from_args, args, allow, nixpkgs_config=nixpkgs_config),
            LocalRevisionTarget(
                staged=args.staged,
                action=ReviewAction(print_result=args.print_result),
            ),
        )
