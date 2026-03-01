from __future__ import annotations

from pathlib import Path

from nixpkgs_review.utils import die, require_env


def ensure_github_token(token: str | None) -> str:
    if not token:
        die(
            "Posting PR comments requires a Github API token; see https://github.com/Mic92/nixpkgs-review#github-api-token"
        )
    return token


def get_current_pr() -> int:
    pr = require_env(
        "PR",
        "PR environment variable not set. Are you in a nixpkgs-review nix-shell?",
    )
    return int(pr)


def get_review_root() -> Path:
    root = require_env(
        "NIXPKGS_REVIEW_ROOT",
        "NIXPKGS_REVIEW_ROOT not set. Are you in a nixpkgs-review nix-shell?",
    )
    return Path(root)
