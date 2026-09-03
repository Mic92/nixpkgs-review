from __future__ import annotations

import functools
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from collections.abc import Callable
    from re import Pattern

HAS_TTY = sys.stdout.isatty()
ROOT = Path(__file__).resolve().parent

type System = str


def color_text(code: int, file: IO[Any] | None = None) -> Callable[[str], None]:
    def wrapper(text: str) -> None:
        if HAS_TTY:
            print(f"\x1b[{code}m{text}\x1b[0m", file=file)
        else:
            print(text, file=file)

    return wrapper


warn = color_text(31, file=sys.stderr)
info = color_text(32)
skipped = color_text(33)
link = color_text(34)


def die(msg: str, exit_code: int = 1) -> NoReturn:
    warn(msg)
    sys.exit(exit_code)


def require_env(var_name: str, error_msg: str) -> str:
    if value := os.environ.get(var_name):
        return value
    die(error_msg)


def to_link(uri: str, text: str) -> str:
    if HAS_TTY:
        return f"\u001b]8;;{uri}\u001b\\{text}\u001b]8;;\u001b\\"
    return text


@dataclass(frozen=True)
class PackageFilter:
    """Filter criteria for selecting/excluding packages."""

    only_packages: set[str] = field(default_factory=set)
    additional_packages: set[str] = field(default_factory=set)
    package_regexes: list[Pattern[str]] = field(default_factory=list)
    skip_packages: set[str] = field(default_factory=set)
    skip_packages_regex: list[Pattern[str]] = field(default_factory=list)


def sh(  # noqa: PLR0913
    command: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        info("$ " + shlex.join(command))
    env = os.environ | env if env else None
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        check=False,
        env=env,
        input=stdin,
        stdout=stdout,
        stderr=stderr,
    )


def escape_attr(attr: str) -> str:
    parts = attr.split(".")
    return ".".join([parts[0], *(f'"{p}"' for p in parts[1:])])


@functools.lru_cache(maxsize=1)
def current_system() -> str:
    system = subprocess.run(
        [
            "nix",
            "--extra-experimental-features",
            "nix-command",
            "eval",
            "--impure",
            "--raw",
            "--expr",
            "builtins.currentSystem",
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return system.stdout


def nix_nom_tool() -> str:
    "Return `nom` if found in $PATH"
    return "nom" if shutil.which("nom") else "nix"


def system_order_key(system: System) -> str:
    """
    For a consistent UI, we keep the platforms sorted as such:
    - x86_64-linux
    - aarch64-linux
    - x86_64-darwin
    - aarch64-darwin

    This helper turns a system name to an alias which can then be sorted in the anti-alphabetical order.
    (i.e. should be used in `sort` with `reverse=True`)

    Example:
    `aarch64-linux` -> `linuxaarch64`
    """
    return "".join(reversed(system.split("-")))


def _zfs_arc_reclaimable_mib() -> int:
    """The ZFS ARC shrinks under pressure but MemAvailable counts it as used."""
    stats = {"size": 0, "c_min": 0}
    try:
        for line in Path("/proc/spl/kstat/zfs/arcstats").read_text().splitlines():
            match line.split():
                case [name, _, value] if name in stats:
                    stats[name] = int(value)
    except OSError:
        return 0
    return max(0, stats["size"] - stats["c_min"]) // (1024 * 1024)


def memory_mib() -> tuple[int, int]:
    """(total, available). Without /proc/meminfo assume half is available."""
    total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1]) // 1024 + _zfs_arc_reclaimable_mib()
                return total, min(available, total)
    except OSError:
        pass
    return total, total // 2


def eval_memory_budget_mib() -> int:
    """Memory the package listing may use by default.

    MemAvailable is only a snapshot and workers overshoot --max-memory-size
    until the next attribute boundary, so keep an absolute reserve for the
    rest of the system and only plan with 60% of what remains."""
    total, available = memory_mib()
    reserve = max(2048, total // 10)
    return max(0, int((available - reserve) * 0.6))


MIN_WORKER_MIB = 2048
MAX_WORKER_MIB = 4096
LONE_WORKER_MIB = 16 * 1024
MAX_AUTO_WORKERS = 32


def default_eval_resources(
    workers: int | None, max_memory_size: int | None
) -> tuple[int, int]:
    """Pick nix-eval-jobs --workers/--max-memory-size for a full nixpkgs listing.

    Measured on nixpkgs: wall time scales ~W^0.74 while each worker (re)start
    only costs ~26s of re-forcing the shared stdenv core, so within a memory
    budget more workers beat more memory per worker. Below ~2GiB single large
    closures (haskellPackages, CUDA) start to thrash, above ~4GiB nothing is
    gained."""
    # leave a core for the desktop and nix-daemon
    cores = max(1, (os.cpu_count() or 1) - 1)
    budget = eval_memory_budget_mib()
    if workers and max_memory_size:
        return workers, max_memory_size
    if workers:
        return workers, max(MIN_WORKER_MIB, min(budget // workers, LONE_WORKER_MIB))
    if max_memory_size is None:
        max_memory_size = max(MIN_WORKER_MIB, min(budget // cores, MAX_WORKER_MIB))
    workers = max(1, min(budget // max_memory_size, cores, MAX_AUTO_WORKERS))
    if workers == 1:
        max_memory_size = max(max_memory_size, min(budget, LONE_WORKER_MIB))
    return workers, max_memory_size
