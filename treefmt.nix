{ lib, inputs, ... }: {
  imports = [
    inputs.treefmt-nix.flakeModule
  ];

  perSystem = { pkgs, ... }: {
    treefmt = {
      # Used to find the project root
      projectRootFile = "flake.lock";

      programs.deno.enable = true;
      programs.mypy.enable = true;
      programs.mypy.directories = {
        "." = {
          directory = ".";
          extraPythonPackages = [
            pkgs.python3.pkgs.pytest
          ];
        };
      };

      settings.formatter = {
        nix = {
          command = "sh";
          options = [
            "-eucx"
            ''
              # First deadnix
              ${lib.getExe pkgs.deadnix} --edit "$@"
              # Then nixpkgs-fmt
              ${lib.getExe pkgs.nixpkgs-fmt} "$@"
            ''
            "--"
          ];
          includes = [ "*.nix" ];
        };

        python = {
          command = "sh";
          options = [
            "-eucx"
            ''
              ${lib.getExe pkgs.ruff} --fix "$@"
              ${lib.getExe pkgs.ruff} format "$@"
            ''
            "--" # this argument is ignored by bash
          ];
          includes = [ "*.py" ];
        };
      };
    };
  };
}
