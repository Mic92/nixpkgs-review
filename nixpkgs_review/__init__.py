import sys

from . import cli


def main() -> None:
    try:
        command = sys.argv[0]
        args = sys.argv[1:]
        cli.main(command, args)
    except KeyboardInterrupt:
        pass
