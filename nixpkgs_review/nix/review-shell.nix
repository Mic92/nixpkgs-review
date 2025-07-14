{
  local-system,
  nixpkgs-config-path,
  # Path to Nix file containing the Nixpkgs config
  attrs-path,
  # Path to Nix file containing a list of attributes to build
  nixpkgs-path,
  # Path to this review's nixpkgs
  local-pkgs ? import nixpkgs-path {
    system = local-system;
    config = import nixpkgs-config-path;
  },
  lib ? local-pkgs.lib,
}:

let

  nixpkgs-config = import nixpkgs-config-path;
  extractPackagesForSystem =
    system: system-attrs:
    let
      system-pkg = import nixpkgs-path {
        inherit system;
        config = nixpkgs-config;
      };
    in
    map (attrString: lib.attrByPath (lib.splitString "." attrString) null system-pkg) system-attrs;
  attrs = lib.flatten (lib.mapAttrsToList extractPackagesForSystem (import attrs-path));
  env =
    local-pkgs.buildEnv {
      name = "env";
      paths = attrs;
      ignoreCollisions = true;
    }
    // lib.optionalAttrs ((lib.functionArgs local-pkgs.buildEnv) ? ignoreSingleFileOutputs) {
      ignoreSingleFileOutputs = true;
    };
in
(import nixpkgs-path { }).mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;
  packages = if builtins.length attrs > 50 then [ env ] else attrs;
}
