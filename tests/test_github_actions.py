from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, mock_open, patch

from nixpkgs_review.cli import main

if TYPE_CHECKING:
    from .conftest import Helpers


@patch("nixpkgs_review.http_requests.urlopen")
def test_post_result(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        root = nixpkgs.path.parent

        os.environ["PR"] = "1"
        os.environ["GITHUB_TOKEN"] = "foo"  # noqa: S105
        os.environ["NIXPKGS_REVIEW_ROOT"] = str(root)
        mock_urlopen.side_effect = [mock_open(read_data="{}")()]

        (root / "report.md").write_text("")
        main("nixpkgs-review", ["post-result"])


@patch("nixpkgs_review.http_requests.urlopen")
def test_merge(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.save_environ(), helpers.nixpkgs() as nixpkgs:
        root = nixpkgs.path.parent
        os.environ["PR"] = "1"
        os.environ["GITHUB_TOKEN"] = "foo"  # noqa: S105
        os.environ["NIXPKGS_REVIEW_ROOT"] = str(root)
        mock_urlopen.side_effect = [
            mock_open(read_data='{ "permissions": { "push": true } }')(),
            mock_open(read_data='{ "node_id": "foo" }')(),
            mock_open(read_data='{ "data": { } }')(),
        ]

        (root / "report.json").write_text(
            '{ "commit": "9e301f2426b8f615a15da1799f111051898172de" }'
        )
        main("nixpkgs-review", ["merge"])


@patch("nixpkgs_review.http_requests.urlopen")
def test_approve(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.save_environ():
        os.environ["PR"] = "1"
        os.environ["GITHUB_TOKEN"] = "foo"  # noqa: S105
        mock_urlopen.side_effect = [mock_open(read_data="{}")()]
        main("nixpkgs-review", ["approve"])
