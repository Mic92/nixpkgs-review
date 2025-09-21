from __future__ import annotations

import sys
from pathlib import Path

from . import cli


def main() -> None:
    try:
        cli.main(Path(sys.argv[0]).name, sys.argv[1:])
    except KeyboardInterrupt:
        sys.exit(130)  # Standard exit code for SIGINT
