{
  local-system,
  nixpkgs-config-path,
  # Path to Nix file containing the Nixpkgs config
  attrs-path,
  # Path to Nix file containing a list of attributes to build
  nixpkgs-path,
  # Path to this review's nixpkgs
  alt-pkgs ? null,
  # Alternative package set name (e.g. pkgsCross.aarch64-multiplatform), or null for default
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
  # When using an alternative package set (cross, musl, static, cuda…),
  # always wrap in buildEnv to avoid nixpkgs platform filtering on nativeBuildInputs
  # which would silently drop cross-compiled packages from the dependency graph.
  # Otherwise, use the buildEnv threshold of 50 to preserve setup hooks in the shell.
  useEnv = alt-pkgs != null || builtins.length attrs > 50;
in
(import nixpkgs-path { }).mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;
  # see test_rev_command_with_pkg_count
  packages = if useEnv then [ env ] else attrs;
}
