from __future__ import annotations

from typing import TYPE_CHECKING

from nixpkgs_review.github import GithubClient
from nixpkgs_review.utils import die

from .utils import ensure_github_token, get_current_pr, get_review_root

if TYPE_CHECKING:
    import argparse


def post_result_command(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    pr = get_current_pr()
    root = get_review_root()

    report = root / "report.md"
    if not report.exists():
        die(f"Report not found in {report}. Are you in a nixpkgs-review nix-shell?")

    report_text = report.read_text()
    github_client.comment_issue(pr, report_text)
