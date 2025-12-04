{
  local-system,
  nixpkgs ? <nixpkgs-wrapper>,
  # Path to Nix file containing the Nixpkgs config
  attrs-path,
  # Path to this review's nixpkgs
  local-pkgs ? import <nixpkgs> {
    system = local-system;
  },
  lib ? local-pkgs.lib,
}:

let

  extractPackagesForSystem =
    system: system-attrs:
    let
      system-pkg = import nixpkgs {
        inherit system;
      };
    in
    map (attrString: lib.attrByPath (lib.splitString "." attrString) null system-pkg) system-attrs;
  attrs = lib.flatten (lib.mapAttrsToList extractPackagesForSystem (import attrs-path));
  supportIgnoreSingleFileOutputs = (lib.functionArgs local-pkgs.buildEnv) ? ignoreSingleFileOutputs;
  env = local-pkgs.buildEnv (
    {
      name = "env";
      paths = attrs;
      ignoreCollisions = true;
    }
    // lib.optionalAttrs supportIgnoreSingleFileOutputs {
      ignoreSingleFileOutputs = true;
    }
  );
in
(import nixpkgs { }).mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;
  packages = [ env ];
}

