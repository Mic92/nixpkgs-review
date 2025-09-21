from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from nixpkgs_review.github import GithubClient
from nixpkgs_review.utils import warn

from .utils import ensure_github_token

if TYPE_CHECKING:
    import argparse


def post_result_command(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    if not (pr_env := os.environ.get("PR")):
        warn("PR environment variable not set. Are you in a nixpkgs-review nix-shell?")
        sys.exit(1)
    pr = int(pr_env)

    if not (report := Path(os.environ["NIXPKGS_REVIEW_ROOT"]) / "report.md").exists():
        warn(f"Report not found in {report}. Are you in a nixpkgs-review nix-shell?")
        sys.exit(1)

    report_text = report.read_text()
    github_client.comment_issue(pr, report_text)
