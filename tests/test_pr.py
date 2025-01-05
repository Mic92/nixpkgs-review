import io
import shutil
import subprocess
import zipfile
from http.client import HTTPMessage
from unittest.mock import MagicMock, Mock, mock_open, patch
from urllib.error import HTTPError

import pytest

from nixpkgs_review.cli import main
from nixpkgs_review.utils import nix_nom_tool

from .conftest import Helpers


@patch("nixpkgs_review.utils.shutil.which", return_value=None)
def test_default_to_nix_if_nom_not_found(mock_shutil: Mock) -> None:
    return_value = nix_nom_tool()
    assert return_value == "nix"
    mock_shutil.assert_called_once()


@pytest.mark.skipif(not shutil.which("nom"), reason="`nom` not found in PATH")
def test_pr_local_eval(helpers: Helpers, capfd: pytest.CaptureFixture) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/1/merge"], check=True)
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/merge"], check=True)

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "1",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        captured = capfd.readouterr()
        assert "$ nom build" in captured.out


@patch("nixpkgs_review.cli.nix_nom_tool", return_value="nix")
def test_pr_local_eval_missing_nom(
    mock_tool: Mock, helpers: Helpers, capfd: pytest.CaptureFixture
) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/1/merge"], check=True)
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/merge"], check=True)

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "1",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        mock_tool.assert_called_once()
        captured = capfd.readouterr()
        assert "$ nix build" in captured.out


def test_pr_local_eval_without_nom(
    helpers: Helpers, capfd: pytest.CaptureFixture
) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/1/merge"], check=True)
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/merge"], check=True)

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "1",
                "--build-graph",
                "nix",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        captured = capfd.readouterr()
        assert "$ nix build" in captured.out


@pytest.mark.skipif(not shutil.which("bwrap"), reason="`bwrap` not found in PATH")
def test_pr_local_eval_with_sandbox(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/1/merge"], check=True)
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/merge"], check=True)

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--sandbox",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "1",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)


@patch("urllib.request.urlopen")
def test_pr_ofborg_eval(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/37200/merge"], check=True)
        subprocess.run(
            ["git", "push", str(nixpkgs.remote), "pull/37200/merge"], check=True
        )

        mock_urlopen.side_effect = [
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_ofborg_eval/github-pull-37200.json"
                )
            )(),
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_ofborg_eval/github-workflows-37200.json"
                )
            )(),
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_ofborg_eval/github-pull-37200-statuses.json"
                )
            )(),
            helpers.read_asset("test_pr_ofborg_eval/gist-37200.txt")
            .encode("utf-8")
            .split(b"\n"),
        ]

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "37200",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)


@patch("urllib.request.urlopen")
def test_pr_github_action_eval(
    mock_urlopen: MagicMock,
    helpers: Helpers,
) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/363128/merge"], check=True)
        subprocess.run(
            ["git", "push", str(nixpkgs.remote), "pull/363128/merge"], check=True
        )

        # Create minimal fake zip archive that could have been generated by the `comparison` GH action.
        mock_zip = io.BytesIO()
        with zipfile.ZipFile(mock_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "changed-paths.json",
                helpers.read_asset(
                    "test_pr_github_action_eval/comparison-changed-paths.json"
                ),
            )
        mock_zip.seek(0)

        mock_urlopen.side_effect = [
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_github_action_eval/github-pull-363128.json"
                )
            )(),
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_github_action_eval/github-workflows-363128.json"
                )
            )(),
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_github_action_eval/github-artifacts-363128.json"
                )
            )(),
            mock_open(read_data=mock_zip.getvalue())(),
        ]

        hdrs = HTTPMessage()
        hdrs.add_header("Location", "http://example.com")
        http_error = HTTPError(
            url="http://example.com",
            code=302,
            msg="Found",
            hdrs=hdrs,
            fp=None,
        )

        with patch(
            "nixpkgs_review.github.no_redirect_opener.open", side_effect=http_error
        ):
            path = main(
                "nixpkgs-review",
                [
                    "pr",
                    "--remote",
                    str(nixpkgs.remote),
                    "--run",
                    "exit 0",
                    "363128",
                ],
            )
            helpers.assert_built(pkg_name="pkg1", path=path)


@patch("nixpkgs_review.review._list_packages_system")
def test_pr_only_packages_does_not_trigger_an_eval(
    mock_eval: MagicMock,
    helpers: Helpers,
) -> None:
    mock_eval.side_effect = RuntimeError
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/363128/merge"], check=True)
        subprocess.run(
            ["git", "push", str(nixpkgs.remote), "pull/363128/merge"], check=True
        )

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--package",
                "pkg1",
                "363128",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
