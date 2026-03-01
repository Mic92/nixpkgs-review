from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nixpkgs_review import git
from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.buildenv import Buildenv
from nixpkgs_review.review import (
    LocalRevisionTarget,
    ReviewAction,
    build_config_from_args,
    review_local_revision,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def rev_command(args: argparse.Namespace) -> Path:
    allow = AllowedFeatures(args.allow)
    with Buildenv(
        allow_aliases=allow.aliases, extra_nixpkgs_config=args.extra_nixpkgs_config
    ) as nixpkgs_config:
        commit = git.verify_commit_hash(args.commit)
        return review_local_revision(
            f"rev-{commit}",
            args,
            partial(build_config_from_args, args, allow, nixpkgs_config=nixpkgs_config),
            LocalRevisionTarget(
                commit=commit,
                action=ReviewAction(print_result=args.print_result),
            ),
        )
