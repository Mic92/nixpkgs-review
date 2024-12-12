{
  inputs,
  ...
}:
{
  imports = [
    inputs.treefmt-nix.flakeModule
  ];

  perSystem =
    { pkgs, ... }:
    {
      treefmt = {
        # Used to find the project root
        projectRootFile = "flake.lock";

        programs = {
          deno.enable =
            pkgs.lib.meta.availableOn pkgs.stdenv.hostPlatform pkgs.deno && !pkgs.deno.meta.broken;
          ruff = {
            format = true;
            check = true;
          };
          mypy.enable = true;
          nixfmt.enable = pkgs.lib.meta.availableOn pkgs.stdenv.buildPlatform pkgs.nixfmt-rfc-style.compiler;
          deadnix.enable = true;
          mypy.directories = {
            "." = {
              directory = ".";
              extraPythonPackages = [
                pkgs.python3Packages.pytest
              ];
            };
          };
        };
      };
    };
}
