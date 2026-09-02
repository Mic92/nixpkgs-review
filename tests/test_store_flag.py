from __future__ import annotations

from pathlib import Path

from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.cli import parse_args
from nixpkgs_review.nix import nix_common_flags
from nixpkgs_review.review import build_config_from_args


def test_store_flags_reach_nix_common_flags() -> None:
    args = parse_args(
        "nixpkgs-review",
        ["rev", "HEAD", "--store", "local?root=/tmp/x", "--eval-store", "auto"],
    )
    build_config = build_config_from_args(
        args, AllowedFeatures([]), nix_path="", nixpkgs_config=Path("/dev/null")
    )
    assert nix_common_flags(build_config)[-4:] == [
        "--store",
        "local?root=/tmp/x",
        "--eval-store",
        "auto",
    ]
