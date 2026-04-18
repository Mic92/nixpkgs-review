from __future__ import annotations

import functools
import re
import subprocess


@functools.lru_cache(maxsize=1)
def nix_version() -> tuple[int, ...]:
    proc = subprocess.run(
        ["nix", "--version"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", proc.stdout)
    if match is None:
        msg = f"Could not parse Nix version from: {proc.stdout!r}"
        raise RuntimeError(msg)
    return tuple(int(group) for group in match.groups() if group is not None)


class AllowedFeatures:
    aliases: bool = False
    ifd: bool = False
    url_literals: bool = False

    def __init__(self, features: list[str]) -> None:
        for feature in features:
            match feature:
                case "aliases":
                    self.aliases = True
                case "ifd":
                    self.ifd = True
                case "url-literals":
                    self.url_literals = True

    def nix_flags(self, experimental_features: list[str] | None = None) -> list[str]:
        flags = []
        features = list(experimental_features or [])
        if not self.url_literals:
            if nix_version() >= (2, 34):
                flags.extend(["--option", "lint-url-literals", "fatal"])
            else:
                features.append("no-url-literals")
        feature_flags = []
        if features:
            feature_flags = ["--extra-experimental-features", " ".join(features)]
        return feature_flags + flags
