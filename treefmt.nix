{ inputs, ... }:
{
  imports = [
    inputs.treefmt-nix.flakeModule
  ];

  perSystem =
    { pkgs, ... }:
    let
      extraPythonFiles = [
        "bin/nix-review"
        "bin/nixpkgs-review"
      ];
    in
    {
      treefmt = {
        # Used to find the project root
        projectRootFile = "flake.lock";

        flakeCheck = pkgs.stdenv.hostPlatform.system != "riscv64-linux";

        programs.deno.enable =
          pkgs.lib.meta.availableOn pkgs.stdenv.hostPlatform pkgs.deno && !pkgs.deno.meta.broken;
        programs.ruff.format = true;
        programs.ruff.check = true;
        programs.actionlint.enable = true;
        programs.yamlfmt.enable = true;
        programs.shellcheck.enable = pkgs.lib.meta.availableOn pkgs.stdenv.buildPlatform pkgs.shellcheck.compiler;
        programs.shfmt.enable = true;
        programs.mypy.enable = true;
        programs.nixfmt.enable = pkgs.lib.meta.availableOn pkgs.stdenv.buildPlatform pkgs.nixfmt.compiler;
        programs.deadnix.enable = true;

        settings.formatter.shfmt.includes = [ "*.envrc" ];

        settings.formatter.ruff-check.includes = extraPythonFiles;
        settings.formatter.ruff-format.includes = extraPythonFiles;

        settings.global.excludes = [
          "tests/assets/*"
          "pyproject.toml"
        ];

        programs.mypy.directories = {
          "." = {
            directory = ".";
            extraPythonPackages = [
              pkgs.python3.pkgs.pytest
            ];
          };
        };
      };
    };
}
