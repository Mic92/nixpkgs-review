from __future__ import annotations


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
