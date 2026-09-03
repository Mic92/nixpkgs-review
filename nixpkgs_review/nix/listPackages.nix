# Enumerate all packages of <nixpkgs> for the given systems, for nix-eval-jobs.
# The first attribute path component is the system so several systems share
# one pool of eval workers.
{
  systems,
  # e.g. "pkgsCross.aarch64-multiplatform" or null
  pkgs ? null,
}:
let
  forSystem =
    system:
    let
      nixpkgs = import <nixpkgs> {
        inherit system;
        config = import (builtins.getEnv "NIXPKGS_CONFIG");
      };
      inherit (nixpkgs) lib;
      root = if pkgs == null then nixpkgs else lib.attrByPath (lib.splitString "." pkgs) { } nixpkgs;
    in
    lib.recurseIntoAttrs root;
in
builtins.listToAttrs (
  map (system: {
    name = system;
    value = forSystem system;
  }) systems
)
