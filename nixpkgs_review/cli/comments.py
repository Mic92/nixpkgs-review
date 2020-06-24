import argparse

from ..github import GithubClient
from .utils import ensure_github_token, get_current_pr


def show_comments(args: argparse.Namespace) -> None:
    github_client = GithubClient(ensure_github_token(args.token))
    comments = github_client.comments(get_current_pr())

    for comment in comments:
        if "diff_hunk" in comment:
            diff_lines = comment["diff_hunk"].split("\n")
            start_line = max(0, comment["original_line"] - 2)
            end_line = comment["original_line"] + 1
            for line in diff_lines[start_line:end_line]:
                print(line)

        print(f"{comment['user']['login']}: {comment['body']}\n")
