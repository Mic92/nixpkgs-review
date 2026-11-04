import pytest

from nixpkgs_review.github import github_repo_from_remote


@pytest.mark.parametrize(
    ("remote", "repo"),
    [
        ("https://github.com/someone/nixpkgs.git/", "someone/nixpkgs"),
        ("git@github.com:someone/nixpkgs.git", "someone/nixpkgs"),
        ("/home/user/nixpkgs", "NixOS/nixpkgs"),
        ("https://gitlab.com/someone/nixpkgs", "NixOS/nixpkgs"),
    ],
)
def test_github_repo_from_remote(remote: str, repo: str) -> None:
    assert github_repo_from_remote(remote) == repo
