from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from nixpkgs_review.utils import ROOT, current_system

from .conftest import TEST_ROOT, Helpers, real_nixpkgs

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("include_tests", [False, True])
@pytest.mark.parametrize(
    ("package", "tests"),
    [
        (
            "selfReferencing",
            {"selfReferencing.tests.self", "selfReferencing.tests.nested.test"},
        ),
        ("overridden", {"overridden.tests.inherited"}),
        ("single", {"single.tests"}),
        ("group", {"group.package.tests.nested.test"}),
    ],
)
def test_eval_tests(
    tmp_path: Path, package: str, tests: set[str], *, include_tests: bool
) -> None:
    with Helpers.nixpkgs():
        fixture = TEST_ROOT / "assets/recursive-tests.nix"
        (tmp_path / "default.nix").write_text(
            f"{{ system, ... }}: import {fixture} {{ "
            f"pkgs = import {real_nixpkgs()} {{ inherit system; config = {{}}; }}; }}"
        )
        config = tmp_path / "config.nix"
        config.write_text("{}")
        attrs = tmp_path / "attrs.json"
        attrs.write_text(json.dumps({current_system(): [package]}))

        result = subprocess.run(
            [
                "nix-instantiate",
                "--eval",
                "--strict",
                "--json",
                "--expr",
                (
                    f"builtins.attrNames (import {ROOT / 'nix/evalAttrs.nix'} {{ "
                    f"attr-json = {attrs}; include-tests = {str(include_tests).lower()}; "
                    f"}}).${{builtins.currentSystem}}"
                ),
            ],
            env=os.environ
            | {"NIX_PATH": f"nixpkgs={tmp_path}", "NIXPKGS_CONFIG": str(config)},
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    name = "group.package" if package == "group" else package
    expected = {name, "recurseForDerivations"}
    if include_tests:
        expected |= tests
    assert set(json.loads(result.stdout)) == expected
