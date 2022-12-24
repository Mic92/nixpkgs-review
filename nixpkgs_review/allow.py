from typing import List


class AllowedFeatures:
    aliases: bool = False
    ifd: bool = False
    url_literals: bool = False

    def __init__(self, features: List[str]) -> None:
        for feature in features:
            # ruff doesn't support match statements yet
            if feature == "aliases":
                self.aliases = True
            elif feature == "ifd":
                self.ifd = True
            elif feature == "url-literals":
                self.url_literals = True
