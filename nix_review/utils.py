import subprocess
import sys
from typing import IO, Any, Callable, List, Optional

HAS_TTY = sys.stdout.isatty()


def color_text(code: int, file: IO[Any] = sys.stdout) -> Callable[[str], None]:
    def wrapper(text: str) -> None:
        if HAS_TTY:
            print(f"\x1b[{code}m{text}\x1b[0m", file=file)
        else:
            print(text, file=file)

    return wrapper


warn = color_text(31, file=sys.stderr)
info = color_text(32)


def sh(command: List[str], cwd: Optional[str] = None) -> None:
    info("$ " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)
