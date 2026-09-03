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
    map (
      attrString:
      let
        attr = lib.attrByPath (lib.splitString "." attrString) null system-pkg;
      in
      attr.all or attr
    ) system-attrs;
  attrs = lib.flatten (lib.mapAttrsToList extractPackagesForSystem (import attrs-path));
  supportIgnoreSingleFileOutputs = (lib.functionArgs local-pkgs.buildEnv) ? ignoreSingleFileOutputs;
  # Always go through buildEnv rather than putting attrs into mkShell directly:
  # - only bin/ ends up on PATH, so setup hooks and propagated inputs of the
  #   reviewed packages don't leak into the shell and mask missing runtime
  #   dependencies of unwrapped programs,
  # - nixpkgs' platform filtering on nativeBuildInputs would otherwise
  #   silently drop cross/foreign-system packages.
  env = local-pkgs.buildEnv (
    {
      name = "env";
      paths = attrs;
      pathsToLink = [ "/bin" ];
      ignoreCollisions = true;
    }
    // lib.optionalAttrs supportIgnoreSingleFileOutputs {
      ignoreSingleFileOutputs = true;
    }
  );
in
(import nixpkgs-path { }).mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;
  packages = [ env ];
}
