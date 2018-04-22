import sys

from . import app


def main() -> None:
    try:
        command = sys.argv[0]
        args = sys.argv[1:]
        app.main(command, args)
    except KeyboardInterrupt:
        pass
