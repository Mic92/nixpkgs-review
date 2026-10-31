from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, mock_open, patch

import pytest

from nixpkgs_review.cli import main
from nixpkgs_review.cli.comments import comments_query
from nixpkgs_review.github import GithubClient, github_repo_from_remote

if TYPE_CHECKING:
    from .conftest import Helpers


@pytest.mark.parametrize(
    ("remote", "repo"),
    [
        ("https://github.com/NixOS/nixpkgs", "NixOS/nixpkgs"),
        ("https://github.com/NixOS/nixpkgs.git", "NixOS/nixpkgs"),
        ("https://github.com/someone/nixpkgs/", "someone/nixpkgs"),
        ("http://github.com/someone/nixpkgs", "someone/nixpkgs"),
        ("git@github.com:someone/nixpkgs.git", "someone/nixpkgs"),
        ("ssh://git@github.com/someone/my-nixpkgs.git", "someone/my-nixpkgs"),
        ("git://github.com/someone/nixpkgs", "someone/nixpkgs"),
        # not on GitHub: keep talking to NixOS/nixpkgs
        ("/home/user/nixpkgs", "NixOS/nixpkgs"),
        ("https://gitlab.com/someone/nixpkgs", "NixOS/nixpkgs"),
        ("https://github.com/NixOS", "NixOS/nixpkgs"),
    ],
)
def test_github_repo_from_remote(remote: str, repo: str) -> None:
    assert github_repo_from_remote(remote) == repo


@patch("nixpkgs_review.http_requests.urlopen")
def test_client_uses_repo(mock_urlopen: MagicMock) -> None:
    mock_urlopen.side_effect = [mock_open(read_data="{}")()]
    GithubClient("foo", "someone/nixpkgs").comment_issue(1, "report")
    req = mock_urlopen.call_args.args[0]
    assert (
        req.full_url == "https://api.github.com/repos/someone/nixpkgs/issues/1/comments"
    )


@patch("nixpkgs_review.http_requests.urlopen")
def test_approve_respects_review_repo(
    mock_urlopen: MagicMock, helpers: Helpers
) -> None:
    with helpers.save_environ():
        os.environ["PR"] = "1"
        os.environ["GITHUB_TOKEN"] = "foo"  # noqa: S105
        os.environ["NIXPKGS_REVIEW_GITHUB_REPO"] = "someone/nixpkgs"
        mock_urlopen.side_effect = [mock_open(read_data="{}")()]
        main("nixpkgs-review", ["approve"])
    req = mock_urlopen.call_args.args[0]
    assert (
        req.full_url == "https://api.github.com/repos/someone/nixpkgs/pulls/1/reviews"
    )


@patch("nixpkgs_review.http_requests.urlopen")
def test_approve_defaults_to_nixpkgs(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.save_environ():
        os.environ["PR"] = "1"
        os.environ["GITHUB_TOKEN"] = "foo"  # noqa: S105
        os.environ.pop("NIXPKGS_REVIEW_GITHUB_REPO", None)
        mock_urlopen.side_effect = [mock_open(read_data="{}")()]
        main("nixpkgs-review", ["approve"])
    req = mock_urlopen.call_args.args[0]
    assert req.full_url == "https://api.github.com/repos/NixOS/nixpkgs/pulls/1/reviews"


def test_comments_query_uses_repo() -> None:
    query = comments_query(42, "someone/nixpkgs")
    assert 'repository(owner: "someone", name: "nixpkgs")' in query
    assert "pullRequest(number: 42)" in query
