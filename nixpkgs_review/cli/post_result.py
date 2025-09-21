from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nixpkgs_review.github import GithubClient
from nixpkgs_review.utils import die, require_env

from .utils import ensure_github_token

if TYPE_CHECKING:
    import argparse


def post_result_command(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    pr = require_env(
        "PR",
        "PR environment variable not set. Are you in a nixpkgs-review nix-shell?",
    )

    root = require_env(
        "NIXPKGS_REVIEW_ROOT",
        "NIXPKGS_REVIEW_ROOT not set. Are you in a nixpkgs-review nix-shell?",
    )
    report = Path(root) / "report.md"
    if not report.exists():
        die(f"Report not found in {report}. Are you in a nixpkgs-review nix-shell?")

    report_text = report.read_text()
    github_client.comment_issue(int(pr), report_text)
