from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from nixpkgs_review.utils import nix_eval_command

if TYPE_CHECKING:
    import pytest

CONFIG = "/home/user/my config.nix"


def test_without_nixpkgs_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIXPKGS_CONFIG", raising=False)
    assert nix_eval_command(["nix-eval-jobs", "--expr", "1 + 1"]) == (
        "nix-eval-jobs --expr '1 + 1'"
    )


def test_with_nixpkgs_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIXPKGS_CONFIG", CONFIG)
    assert nix_eval_command(["nix-eval-jobs", "--expr", "1 + 1"]) == (
        "NIXPKGS_CONFIG='/home/user/my config.nix' nix-eval-jobs --expr '1 + 1'"
    )


def test_printed_line_sets_nixpkgs_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIXPKGS_CONFIG", CONFIG)
    line = nix_eval_command(["printenv", "NIXPKGS_CONFIG"])
    monkeypatch.delenv("NIXPKGS_CONFIG")
    out = subprocess.run(
        ["sh", "-c", line], capture_output=True, text=True, check=True
    ).stdout
    assert out == CONFIG + "\n"
