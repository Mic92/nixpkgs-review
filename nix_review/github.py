import urllib.parse
import json
from collections import defaultdict
import urllib.request
from typing import Any, DefaultDict, Dict, Optional, Set


class GithubClient:
    def __init__(self, api_token: Optional[str]) -> None:
        self.api_token = api_token

    def get(self, path: str) -> Any:
        url = urllib.parse.urljoin("https://api.github.com/", path)
        req = urllib.request.Request(url)
        if self.api_token:
            req.add_header("Authorization", f"token {self.api_token}")
        return json.loads(urllib.request.urlopen(req).read())

    def get_borg_eval_gist(self, pr: Dict[str, Any]) -> Optional[Dict[str, Set[str]]]:
        packages_per_system: DefaultDict[str, Set[str]] = defaultdict(set)
        statuses = self.get(pr["statuses_url"])
        for status in statuses:
            url = status.get("target_url", "")
            if (
                status["description"] == "^.^!"
                and status["creator"]["login"] == "GrahamcOfBorg"
                and url != ""
            ):
                url = urllib.parse.urlparse(url)
                raw_gist_url = (
                    f"https://gist.githubusercontent.com/GrahamcOfBorg{url.path}/raw/"
                )
                for line in urllib.request.urlopen(raw_gist_url):
                    if line == b"":
                        break
                    system, attribute = line.decode("utf-8").split()
                    blacklist = [
                        # workaround https://github.com/NixOS/ofborg/issues/269
                        "tests.nixos-functions.nixos-test",
                        "tests.nixos-functions.nixosTest-test",
                    ]
                    if attribute in blacklist:
                        continue
                    packages_per_system[system].add(attribute)
                return packages_per_system
        return None
