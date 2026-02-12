{
  mkShell,
  python3,
  git,
  nix,
  nix-output-monitor,
  bubblewrap,
  delta,
  treefmt,
  nixfmt,
  lib,
  stdenv,
}:

mkShell {
  name = "nixpkgs-review-dev";

  buildInputs = [
    # Python development
    (python3.withPackages (ps: [
      # Project dependencies
      ps.argcomplete

      # Development dependencies
      ps.pytest
      ps.pytest-xdist
      ps.mypy
      ps.ruff

      # Build system
      ps.setuptools
    ]))

    # Project runtime dependencies
    git
    nix

    # Optional tools
    delta # for nicer diff display

    # Development tools
    treefmt
  ]
  ++ lib.optionals (!stdenv.hostPlatform.isRiscV64) [ nix-output-monitor ]
  ++ lib.optionals stdenv.hostPlatform.isLinux [ bubblewrap ]
  ++ lib.optionals (!stdenv.hostPlatform.isRiscV64) [ nixfmt ];

  shellHook = ''
    echo "nixpkgs-review development shell"
    echo "Run tests with: pytest"
    echo "Format code with: nix fmt"
    echo "Type check with: mypy nixpkgs_review"
  '';
}
