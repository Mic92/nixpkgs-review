from pathlib import Path

from .utils import System, sh


def _ci_command(
    worktree_dir: Path,
    command: str,
    output_dir: str,
    options: dict[str, str] | None = None,
    args: dict[str, str] | None = None,
) -> None:
    cmd: list[str] = [
        "nix-build",
        str(worktree_dir.joinpath(Path("ci"))),
        "-A",
        f"eval.{command}",
    ]
    if options is not None:
        for option, value in options.items():
            cmd.extend([option, value])

    if args is not None:
        for arg, value in args.items():
            cmd.extend(["--arg", arg, value])

    cmd.extend(["--out-link", output_dir])
    sh(cmd, capture_output=True)


def local_eval(
    worktree_dir: Path,
    systems: set[System],
    max_jobs: int,
    n_cores: int,
    chunk_size: int,
    output_dir: str,
) -> None:
    options: dict[str, str] = {
        "--max-jobs": str(max_jobs),
        "--cores": str(n_cores),
    }

    eval_systems: str = " ".join(f'"{system}"' for system in systems)
    eval_systems = f"[{eval_systems}]"
    args: dict[str, str] = {
        "evalSystems": eval_systems,
        "chunkSize": str(chunk_size),
    }

    _ci_command(
        worktree_dir=worktree_dir,
        command="full",
        options=options,
        args=args,
        output_dir=output_dir,
    )


def compare(
    worktree_dir: Path,
    before_dir: str,
    after_dir: str,
    output_dir: str,
) -> None:
    args: dict[str, str] = {
        "beforeResultDir": before_dir,
        "afterResultDir": after_dir,
    }
    _ci_command(
        worktree_dir=worktree_dir,
        command="compare",
        args=args,
        output_dir=output_dir,
    )
