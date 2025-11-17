from __future__ import annotations

from typing import TYPE_CHECKING

from nixpkgs_review.github import GithubClient

from .utils import ensure_github_token, get_current_pr

if TYPE_CHECKING:
    import argparse


def merge_command(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    if any(
        label["name"] == "2.status: merge-bot eligible"
        for label in github_client.labels()
    ):
        github_client.comment_issue(get_current_pr(), "@NixOS/nixpkgs-merge-bot merge")
    else:
        github_client.merge_pr(get_current_pr())

