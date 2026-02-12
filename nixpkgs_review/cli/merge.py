from __future__ import annotations

from json import loads
from typing import TYPE_CHECKING

from nixpkgs_review.github import GithubClient
from nixpkgs_review.utils import die

from .utils import ensure_github_token, get_current_pr, get_review_root

if TYPE_CHECKING:
    import argparse


def merge_command(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    pr_number = get_current_pr()
    path = get_review_root() / "report.json"

    if not path.is_file():
        die(f"Could not find review report file '{path}'")

    report = loads(path.read_text())

    if not isinstance(report, dict):
        die(f"'{path}' is not a JSON object")
    if "commit" not in report:
        die(f"'{path}' does not contain a 'commit' field")
    expected_head_sha = report["commit"]
    if not isinstance(expected_head_sha, str):
        die(
            f"expected {path}'s 'commit' field to be a str, "
            f"got {type(expected_head_sha)}"
        )
    expected_head_sha: str

    if github_client.is_nixpkgs_committer():
        github_client.merge_pr(pr_number, expected_head_sha)
    elif any(
        label["name"] == "2.status: merge-bot eligible"
        for label in github_client.labels(pr_number)
    ):
        if github_client.pull_request(pr_number)["head"]["sha"] == expected_head_sha:
            github_client.comment_issue(pr_number, "@NixOS/nixpkgs-merge-bot merge")
        else:
            die(
                "The pull request has changed since the review started. "
                "Please review the changes and either start another "
                "nixpkgs-review or command a merge yourself."
            )
    else:
        die(
            "You are not a committer, and this PR has not been marked as "
            "eligible for merge bot use."
        )
