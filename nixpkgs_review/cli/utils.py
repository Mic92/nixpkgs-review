import os
import sys

from ..utils import warn


def ensure_github_token(token: str | None) -> str:
    if not token:
        warn(
            "Posting PR comments requires a Github API token; see https://github.com/Mic92/nixpkgs-review#github-api-token"
        )
        sys.exit(1)
    return token


def get_current_pr() -> int:
    pr = os.environ.get("PR", None)
    if pr is None:
        warn("PR environment variable not set. Are you in a nixpkgs-review nix-shell?")
        sys.exit(1)
    return int(pr)
