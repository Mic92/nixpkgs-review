from __future__ import annotations

import sys
from pathlib import Path

from . import cli


def main() -> None:
    try:
        command = Path(sys.argv[0]).name
        args = sys.argv[1:]
        cli.main(command, args)
    except KeyboardInterrupt:
        pass
