from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from nixpkgs_review.allow import AllowedFeatures
from nixpkgs_review.cli import main, parse_args
from nixpkgs_review.nix import BuildConfig, nix_common_flags, option_flags
from nixpkgs_review.review import build_config_from_args

if TYPE_CHECKING:
    import pytest

    from .conftest import Helpers


def test_option_flags_expansion() -> None:
    assert option_flags((("cores", "4"), ("max-jobs", "2"))) == [
        "--option",
        "cores",
        "4",
        "--option",
        "max-jobs",
        "2",
    ]


def test_option_flags_empty() -> None:
    assert option_flags(()) == []


def test_option_flags_preserves_order_on_repeated_name() -> None:
    # Nix applies --option left-to-right, last occurrence wins; we must not
    # dedupe or reorder, so the same last-wins behavior falls out naturally.
    assert option_flags((("cores", "4"), ("cores", "8"))) == [
        "--option",
        "cores",
        "4",
        "--option",
        "cores",
        "8",
    ]


def _build_config(options: tuple[tuple[str, str], ...] = ()) -> BuildConfig:
    return BuildConfig(
        allow=AllowedFeatures([]),
        nix_path="",
        nixpkgs_config=Path("/dev/null"),
        options=options,
    )


def test_nix_common_flags_includes_extra_options() -> None:
    flags = nix_common_flags(_build_config((("cores", "4"),)))
    assert flags[-3:] == ["--option", "cores", "4"]


def test_parse_args_option_flag() -> None:
    args = parse_args(
        "nixpkgs-review",
        ["rev", "HEAD", "--option", "cores", "4", "--option", "max-jobs", "2"],
    )
    assert args.options == [["cores", "4"], ["max-jobs", "2"]]


def test_parse_args_option_flag_defaults_empty() -> None:
    args = parse_args("nixpkgs-review", ["rev", "HEAD"])
    assert args.options == []


def test_build_config_from_args_carries_options() -> None:
    args = parse_args(
        "nixpkgs-review",
        ["rev", "HEAD", "--option", "cores", "4", "--option", "max-jobs", "2"],
    )
    build_config: BuildConfig = build_config_from_args(
        args, AllowedFeatures([]), nix_path="", nixpkgs_config=Path("/dev/null")
    )
    assert build_config.options == (("cores", "4"), ("max-jobs", "2"))


def test_option_flag_end_to_end(
    helpers: Helpers, capsys: pytest.CaptureFixture[str]
) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        path = main(
            "nixpkgs-review",
            [
                "rev",
                "HEAD",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--build-graph",
                "nix",
                "--option",
                "cores",
                "1",
            ],
        )
        helpers.assert_built(path, "pkg1")
        assert "--option cores 1" in capsys.readouterr().out
