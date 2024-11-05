{
  local-system,
  nixpkgs-config-path,
  # Path to Nix file containing the Nixpkgs config
  attrs-path,
  # Whether to ignore single-file outputs
  ignoreSingleFileOutputs,
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
    let
      supportIgnoreSingleFileOutputs = (lib.functionArgs local-pkgs.buildEnv) ? ignoreSingleFileOutputs;
    in
    local-pkgs.buildEnv (
      {
        name = "env";
        paths = attrs;
        ignoreCollisions = true;
      }
      //
        lib.warnIf (!supportIgnoreSingleFileOutputs && ignoreSingleFileOutputs)
          "The reviewing Nixpkgs's buildEnv doesn't support ignoreSingleFileOutputs. Assuming --check-single-file-outputs"
          (
            lib.optionalAttrs supportIgnoreSingleFileOutputs {
              inherit ignoreSingleFileOutputs;
            }
          )
    );
in
(import nixpkgs-path { }).mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;
  packages = if !ignoreSingleFileOutputs || builtins.length attrs > 50 then [ env ] else attrs;
}
