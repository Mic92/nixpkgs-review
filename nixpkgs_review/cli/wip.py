import argparse
from pathlib import Path

from ..allow import AllowedFeatures
from ..buildenv import Buildenv
from ..review import review_local_revision
from ..utils import verify_commit_hash


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
