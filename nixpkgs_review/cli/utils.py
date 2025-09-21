from __future__ import annotations

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
