from unittest.mock import patch

from nixpkgs_review.allow import AllowedFeatures


def test_nix_flags_disable_url_literals_by_default() -> None:
    with patch("nixpkgs_review.allow.nix_version", return_value=(2, 34, 0)):
        allow = AllowedFeatures([])

        assert allow.nix_flags(experimental_features=["nix-command"]) == [
            "--extra-experimental-features",
            "nix-command",
            "--option",
            "lint-url-literals",
            "fatal",
        ]


def test_nix_flags_omit_url_literal_lint_when_allowed() -> None:
    with patch("nixpkgs_review.allow.nix_version", return_value=(2, 34, 0)):
        allow = AllowedFeatures(["url-literals"])

        assert allow.nix_flags(experimental_features=["nix-command"]) == [
            "--extra-experimental-features",
            "nix-command",
        ]


def test_nix_flags_without_experimental_features() -> None:
    with patch("nixpkgs_review.allow.nix_version", return_value=(2, 34, 0)):
        allow = AllowedFeatures([])

        assert allow.nix_flags() == ["--option", "lint-url-literals", "fatal"]


def test_nix_flags_fallback_to_experimental_feature_on_older_nix() -> None:
    with patch("nixpkgs_review.allow.nix_version", return_value=(2, 33, 0)):
        allow = AllowedFeatures([])

        assert allow.nix_flags(experimental_features=["nix-command"]) == [
            "--extra-experimental-features",
            "nix-command no-url-literals",
        ]
